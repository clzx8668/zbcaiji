"""
爬虫核心引擎
负责：打开站点首页 → 智能分析搜索入口 → 执行搜索 → 解析结果列表 → 逐条抓取详情
"""
import json
import random
import time
import traceback
from typing import List, Optional
from loguru import logger
from config.settings import settings
from core.anti_detect import random_delay, human_type, human_mouse_move, random_scroll, detect_captcha, detect_auto_verify, wait_for_auto_verify
from core.browser import BrowserFactory
from core.extractor import Extractor
from core.search_analyzer import SearchAnalyzer, SearchConfig
from sites import get_adapter
from utils.excel_reader import SiteConfig
from utils.helpers import random_sleep, url_hash


class CrawlResult:
    """单次爬取结果"""
    def __init__(self, url: str, title: str = "", item_type: str = ""):
        self.url = url
        self.url_hash = url_hash(url)
        self.title = title
        self.item_type = item_type
        self.publish_date = ""
        self.amount = ""
        self.source_org = ""
        self.detail_text = ""
        self.keywords_matched = ""


class Crawler:
    """
    爬虫引擎。
    每个 Crawler 实例对应一个站点的一次爬取任务。
    """

    def __init__(
        self,
        config: SiteConfig,
        force_reanalyze: bool = False,
        no_interact: bool = False,
        engine: Optional[str] = None,
        session_name: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ):
        """
        Args:
            config: 站点配置
            force_reanalyze: 是否强制重新分析搜索入口
            no_interact: 是否非交互模式（跳过人工确认）
            engine: 浏览器引擎 (playwright/camoufox)，默认 None 取 settings
            session_name: 浏览器会话名，用于持久化登录状态
            timeout_seconds: 单次任务总时长上限（秒），默认取 settings.CRAWL_MAX_SECONDS
        """
        self.config = config
        self.engine = engine or settings.BROWSER_ENGINE
        self.session_name = session_name or config.site_name  # 默认用站点名
        self.extractor = Extractor()
        self.search_analyzer = SearchAnalyzer()
        self.force_reanalyze = force_reanalyze
        self.no_interact = no_interact
        # 站点专用适配器（命中则优先使用，避免每次重新猜测）
        adapter_cls = get_adapter(config.site_name)
        self.adapter = adapter_cls(config) if adapter_cls else None
        # 任务总时长截止线，防止后台任务无限卡住（如交互阻塞/网络异常）
        self._deadline = time.monotonic() + (timeout_seconds or settings.CRAWL_MAX_SECONDS)
        self.results: List[CrawlResult] = []
        self._current_keyword = ""  # 当前正在搜索的关键词（用于 keywords_matched）
        # 异常计数器（Task 5）
        self._empty_page_count = 0      # 连续空结果页数
        self._http_error_count = 0      # HTTP 异常次数
        self._blocked = False            # 站点是否被熔断
        self._config_error: Optional[Exception] = None  # 配置类错误（如 search_url 非法）
        self._page: Optional[Any] = None
        self._context: Optional[Any] = None  # 保存 context 引用用于保存 session

    def _is_expired(self) -> bool:
        """是否已达到任务总时长上限"""
        return time.monotonic() > self._deadline

    @staticmethod
    def _wait_settled(page, timeout_ms: int = 30000):
        """等待页面基本稳定：networkidle 超时降级为 domcontentloaded。
        部分站点存在轮询组件（聊天/统计脚本）导致 networkidle 永不触发，不能因此卡死。"""
        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            try:
                page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass

    def crawl(self) -> List[CrawlResult]:
        """
        执行完整爬取流程

        Returns:
            爬取结果列表
        """
        logger.info(f"=== 开始爬取: {self.config.site_name} ===")
        logger.info(f"URL: {self.config.site_url}")
        logger.info(f"关键词: {self.config.keywords_str}")
        logger.info(f"类型: {self.config.search_type}")

        try:
            # 根据引擎直接调用，避免 create() 中间层可能的代理传递问题
            if self.engine == "camoufox":
                # 交互模式（手动 CLI）打开可见浏览器，方便扫码登录；后台调度保持无头
                driver, browser, ctx = BrowserFactory.create_camoufox(headless=self.no_interact)
                self._crawl_with_camoufox(browser)
            else:
                driver, browser, ctx = BrowserFactory.create_playwright(
                    headless=self.no_interact,
                    proxy=None,
                    session_name=self.session_name,
                )
                self._context = ctx  # 保存 context 引用
                self._crawl_with_playwright(ctx)

            # 爬取完成后自动保存会话（保留登录状态供下次使用）
            if ctx and self.engine != "camoufox":
                BrowserFactory.save_session(ctx, self.session_name)

            try:
                self._cleanup(driver, browser, ctx)
            except Exception:
                pass

        except Exception as e:
            logger.error(f"爬取 {self.config.site_name} 失败: {e}")
            logger.debug(traceback.format_exc())
            # 配置类错误要向上抛，让任务记录为 failed 并带上明确原因
            if self._config_error:
                raise self._config_error

        logger.info(f"=== {self.config.site_name} 完成，共 {len(self.results)} 条结果 ===")
        return self.results

    def _crawl_with_playwright(self, context):
        """Playwright 引擎的爬取逻辑（支持多关键词逐个搜索）"""
        page = context.new_page()
        keywords = self.config.keywords or [""]
        # 通用启发式站点仅搜第一个关键词（避免反复重分析首页）；模板/适配器站点逐词搜索
        if not (self.config.search_url or self.adapter):
            keywords = keywords[:1]

        for kw in keywords:
            if self._is_expired():
                logger.warning(f"[{self.config.site_name}] 已达任务时长上限，停止后续关键词")
                break
            self._current_keyword = kw
            logger.info(f"[{self.config.site_name}] === 关键词: {kw or '(空)'} ===")

            # 若配置了 search_url 或命中站点适配器，直接导航到搜索页
            if self.config.search_url or self.adapter:
                self._analyze_and_search(page, kw)
            else:
                # Step 1: 打开站点首页，智能分析搜索入口，执行搜索
                logger.debug(f"打开站点首页: {self.config.site_url}")
                page.goto(self.config.site_url, timeout=settings.CRAWL_TIMEOUT * 1000)
                random_delay(1, 5)
                page.wait_for_load_state("networkidle", timeout=30000)

                if not self._handle_auto_verify(page):
                    if detect_captcha(page):
                        self._handle_captcha()

                human_mouse_move(page)
                random_scroll(page)
                random_delay(0.5, 2)

                self._analyze_and_search(page, kw)

            # Step 2: 解析结果列表 & 翻页
            self._parse_results_and_paginate(page, context)

    def _crawl_with_camoufox(self, browser):
        """Camoufox 引擎的爬取逻辑（支持多关键词逐个搜索）"""
        page = browser.new_page()
        keywords = self.config.keywords or [""]
        if not (self.config.search_url or self.adapter):
            keywords = keywords[:1]

        for kw in keywords:
            if self._is_expired():
                break
            self._current_keyword = kw
            logger.info(f"[{self.config.site_name}] === 关键词: {kw or '(空)'} ===")

            if self.config.search_url or self.adapter:
                self._analyze_and_search(page, kw)
            else:
                logger.debug(f"打开站点首页: {self.config.site_url}")
                page.goto(self.config.site_url, timeout=settings.CRAWL_TIMEOUT * 1000)
                random_delay(1, 5)
                page.wait_for_load_state("networkidle", timeout=30000)

                if not self._handle_auto_verify(page):
                    if detect_captcha(page):
                        self._handle_captcha()

                human_mouse_move(page)
                random_scroll(page)
                random_delay(0.5, 2)

                self._analyze_and_search(page, kw)

            # Step 2: 解析结果列表 & 翻页
            self._parse_results_and_paginate(page, None)

    def _analyze_and_search(self, page, keyword: str = ""):
        """
        搜索入口：优先使用 Excel 配置的 search_url，否则智能分析。
        """
        site_name = self.config.site_name

        # 如果 Excel 中配置了 search_url 模板，直接使用
        if self.config.search_url:
            self._search_via_template_url(page, keyword)
            return

        # 命中站点适配器：使用适配器构造的搜索 URL
        kw_text = keyword or (self.config.keywords[0] if self.config.keywords else "")
        if self.adapter:
            adapter_url = self.adapter.get_search_url(kw_text)
            if adapter_url:
                logger.info(f"[{site_name}] 使用适配器搜索: {adapter_url[:100]}")
                page.goto(adapter_url, timeout=settings.CRAWL_TIMEOUT * 1000)
                self._wait_settled(page)
                self._handle_auto_verify(page)
                human_mouse_move(page)
                random_scroll(page)
                random_delay(1, 3)
                return

        # 否则走智能搜索分析流程
        search_config = self.search_analyzer.analyze(
            page, site_name, self.config.site_url, force=self.force_reanalyze
        )

        # 只用第一个关键词搜索，避免多关键词 AND 搜索导致结果骤减
        logger.info(f"[{site_name}] 搜索方式: {search_config.method}, 关键词: {kw_text}")

        # 根据分析结果执行搜索
        if search_config.method == "GET":
            self._search_via_get(page, search_config, kw_text)
        elif search_config.method in ("POST", "FORM"):
            self._search_via_form(page, search_config, kw_text)
        elif search_config.method == "LINK":
            self._search_via_link(page, search_config, kw_text)
        else:
            # 兜底：使用通用搜索逻辑
            self._perform_search(page)

    def _search_via_template_url(self, page, keyword: str = ""):
        """
        使用 Excel 中配置的 search_url 模板直接导航。
        支持占位符: {keyword}, {start_date}, {end_date}, 
                   {start_date_colon}, {end_date_colon}
        注意：多个关键词时只用第一个进行搜索（避免 AND 搜索导致结果过少），
              其他关键词用于后续结果过滤。
        """
        import urllib.parse

        template = self.config.search_url
        kw_text = keyword or (self.config.keywords[0] if self.config.keywords else "")

        # 替换占位符
        url = template.replace("{keyword}", urllib.parse.quote(kw_text))
        url = url.replace("{start_date}", self.config.date_start)
        url = url.replace("{end_date}", self.config.date_end)
        url = url.replace("{start_date_colon}", self.config.date_start_colon)
        url = url.replace("{end_date_colon}", self.config.date_end_colon)

        # 处理相对 URL（以 / 开头的模板）
        if url.startswith("/"):
            from urllib.parse import urlparse
            parsed = urlparse(page.url)
            url = f"{parsed.scheme}://{parsed.netloc}{url}"

        # 校验 URL 合法性，避免把非 URL 内容（如误填的关键词）直接交给 goto
        from utils.helpers import is_valid_url
        if not is_valid_url(url):
            err = ValueError(
                f"[{self.config.site_name}] search_url 不是合法的 http(s) 地址，"
                f"请检查是否把关键词误填到了 search_url 字段: {template[:80]}"
            )
            self._config_error = err
            raise err

        logger.info(f"[{self.config.site_name}] 使用模板 URL 搜索: {url[:120]}...")
        page.goto(url, timeout=settings.CRAWL_TIMEOUT * 1000)
        random_delay(2, 4)
        self._wait_settled(page)
        self._handle_auto_verify(page)
        human_mouse_move(page)
        random_scroll(page)
        random_delay(1, 3)

    def _search_via_get(self, page, search_config: SearchConfig, keyword: str):
        """GET 方式：直接构造搜索 URL 跳转"""
        url_template = search_config.search_url_template
        if not url_template:
            logger.warning("GET 方式但无 URL 模板，使用默认搜索")
            self._perform_search(page)
            return

        # 构造搜索 URL
        import urllib.parse
        encoded_keyword = urllib.parse.quote(keyword)
        search_url = url_template.replace("{keyword}", encoded_keyword)

        # 处理相对 URL
        if search_url.startswith("/"):
            from urllib.parse import urlparse
            parsed = urlparse(page.url)
            search_url = f"{parsed.scheme}://{parsed.netloc}{search_url}"

        # 校验 URL 合法性
        from utils.helpers import is_valid_url
        if not is_valid_url(search_url):
            logger.warning(f"[{self.config.site_name}] 分析得到的搜索 URL 不合法，改用默认搜索: {search_url[:80]}")
            self._perform_search(page)
            return

        logger.info(f"[{self.config.site_name}] GET 搜索 URL: {search_url}")
        page.goto(search_url, timeout=settings.CRAWL_TIMEOUT * 1000)
        random_sleep(1, 3)
        page.wait_for_load_state("networkidle", timeout=30000)

    def _search_via_form(self, page, search_config: SearchConfig, keyword: str):
        """POST/Form 方式：定位表单填写关键词并提交（支持 SPA + API 拦截）"""
        field_sel = search_config.keyword_field_selector
        submit_sel = search_config.submit_selector
        search_url_tmpl = search_config.search_url_template
        old_url = page.url

        if field_sel or search_url_tmpl:
            try:
                # 先用 Playwright 定位输入框
                input_el = None
                try:
                    input_el = page.query_selector(field_sel) if field_sel else None
                except Exception:
                    pass

                if not input_el:
                    try:
                        input_el = page.get_by_placeholder("请输入关键字进行搜索").first
                        if not input_el:
                            input_el = page.get_by_placeholder("搜索").first
                    except Exception:
                        pass

                if input_el and input_el.is_visible():
                    # Task 3: 拟人化输入
                    logger.debug(f"拟人化输入: {keyword}")
                    human_type(page, field_sel or 'input[placeholder]', keyword)

                    # 拟人化延迟
                    random_delay(0.7, 2.5)

                    # 点击搜索按钮（SPA 兼容）
                    submitted = False

                    if submit_sel:
                        try:
                            btn = page.query_selector(submit_sel)
                            if btn and btn.is_visible():
                                btn.click()
                                submitted = True
                                logger.debug(f"已点击提交按钮: {submit_sel}")
                        except Exception:
                            pass

                    if not submitted:
                        for btn_text in ["搜索", "查询"]:
                            try:
                                btn = page.get_by_text(btn_text, exact=True).first
                                if btn and btn.is_visible():
                                    btn.click()
                                    submitted = True
                                    logger.debug(f"已点击搜索文字按钮: {btn_text}")
                                    break
                            except Exception:
                                pass

                    if not submitted:
                        try:
                            result = page.evaluate("""() => {
                                const btn = document.querySelector(
                                    '.search-box button, .n-search button, button[type="submit"]'
                                );
                                if (btn) {
                                    btn.dispatchEvent(new MouseEvent('click', {
                                        bubbles: true, cancelable: true
                                    }));
                                    btn.click();
                                    return true;
                                }
                                return false;
                            }""")
                            if result:
                                submitted = True
                                logger.debug("已通过 JS dispatch 点击搜索按钮")
                        except Exception:
                            pass

                    if not submitted:
                        input_el.press("Enter")
                        logger.debug("已按 Enter 提交")

                    # 搜索后拟人化等待 + 鼠标滚动
                    human_mouse_move(page)
                    random_scroll(page)

                    # 等待结果（检测 URL 变化 + 新 API 请求）
                    random_delay(2, 4)
                    url_changed = False
                    try:
                        page.wait_for_url(lambda u: u != old_url, timeout=8000)
                        url_changed = True
                        logger.debug("检测到 URL 变化")
                    except Exception:
                        pass
                    page.wait_for_load_state("networkidle", timeout=30000)
                    random_delay(2, 3)

                    # Task 4: API 拦截兜底 —— 搜索后检查是否真的触发了结果
                    if not url_changed and page.url == old_url:
                        logger.info("搜索未触发 URL 变化，尝试 API 拦截式搜索...")
                        if self._try_api_search(page, keyword):
                            return
                        # Task 6: 搜索无变化，人工介入
                        self._handle_search_noop(page)
                    return

            except Exception as e:
                logger.warning(f"FORM 搜索失败: {e}")

        # 降级：尝试 GET URL
        if search_url_tmpl:
            try:
                import urllib.parse
                search_url = search_url_tmpl.replace("{keyword}", urllib.parse.quote(keyword))
                if search_url.startswith("/"):
                    from urllib.parse import urlparse
                    parsed = urlparse(page.url)
                    search_url = f"{parsed.scheme}://{parsed.netloc}{search_url}"
                from utils.helpers import is_valid_url
                if not is_valid_url(search_url):
                    logger.warning(f"[{self.config.site_name}] FORM 降级的搜索 URL 不合法，跳过: {search_url[:80]}")
                    self._perform_search(page)
                    return
                logger.info(f"FORM 降级到 GET URL: {search_url}")
                page.goto(search_url, timeout=settings.CRAWL_TIMEOUT * 1000)
                random_delay(1, 3)
                page.wait_for_load_state("networkidle", timeout=30000)
                return
            except Exception as e:
                logger.warning(f"GET 降级也失败: {e}")

        self._perform_search(page)

    def _search_via_link(self, page, search_config: SearchConfig, keyword: str):
        """LINK 方式：首页无搜索框，需要点击进入搜索页"""
        nav_sel = search_config.navigation_link
        if nav_sel:
            try:
                link = page.query_selector(nav_sel)
                if link and link.is_visible():
                    link.click()
                    logger.debug(f"已点击搜索入口: {nav_sel}")
                    random_sleep(1, 3)
                    page.wait_for_load_state("networkidle", timeout=30000)
                    # 进入搜索页后再尝试通用搜索
                    self._perform_search(page)
                    return
            except Exception as e:
                logger.warning(f"搜索入口链接点击失败: {e}")

        # 降级
        self._perform_search(page)

    def _parse_results_and_paginate(self, page, context):
        """解析结果列表并翻页抓取详情，含渐进延迟 + 熔断"""
        page_num = 1
        while page_num <= settings.MAX_PAGES and not self._blocked and not self._is_expired():
            logger.debug(f"正在解析第 {page_num} 页结果列表...")
            if self.adapter:
                # 适配器站点：搜索后已等待页面稳定，直接短延时解析
                random_delay(1, 2)
            else:
                # 等待结果容器出现（AJAX 页面可能延迟渲染）
                try:
                    page.wait_for_selector(
                        "ul[class*='result'], .result-list, table tbody, .vT-srch-result-list",
                        timeout=10000
                    )
                except Exception:
                    logger.debug("结果容器等待超时，尝试直接解析")
                random_delay(1, 3)  # 额外等待 AJAX 渲染
            items = self._parse_result_list(page)
            if not items:
                # Task 5: 连续空页计数
                self._empty_page_count += 1
                if self._empty_page_count >= 3:
                    logger.warning(
                        f"[{self.config.site_name}] 连续 {self._empty_page_count} 页无结果，"
                        "触发熔断终止。建议：检查搜索是否生效，或站点是否有动态加密/WAF 拦截"
                    )
                    break
                logger.debug(f"第 {page_num} 页无结果，继续翻页 (空页计数: {self._empty_page_count})")
            else:
                self._empty_page_count = 0  # 有结果时重置

            # 逐条抓取详情
            self._fetch_details(page, context, items)

            # 尝试翻页（渐进递增延迟）
            if not self._go_next_page(page):
                break
            page_num += 1
            # Task 3: 翻页间隔递增
            progressive_delay = 1 + page_num * random.uniform(0.5, 2)
            random_delay(progressive_delay, progressive_delay + 3)
            human_mouse_move(page)
            random_scroll(page)

    def _perform_search(self, page, field_selector: str = ""):
        """
        模拟搜索操作：填写关键词 + 设置时间 + 点击搜索

        这是通用实现，适配大多数招标站的搜索表单。
        特殊站点可在 sites/ 目录下覆盖此方法。
        """
        try:
            # 如果有精确选择器，优先使用
            if field_selector:
                keyword_selectors = [field_selector]
            else:
                keyword_selectors = [
                    'input[name*="keyword"]',
                    'input[name*="key"]',
                    'input[name*="search"]',
                    'input[placeholder*="关键词"]',
                    'input[placeholder*="搜索"]',
                    'input[id*="keyword"]',
                    'input[id*="search"]',
                    'input[class*="search"]',
                ]

            keyword_input = None
            for sel in keyword_selectors:
                try:
                    keyword_input = page.query_selector(sel)
                    if keyword_input and keyword_input.is_visible():
                        break
                except Exception:
                    continue

            if keyword_input:
                # 只用第一个关键词搜索
                kw_text = self.config.keywords[0] if self.config.keywords else ""
                keyword_input.click()
                random_sleep(0.3, 0.8)
                keyword_input.fill(kw_text)
                logger.debug(f"已输入关键词: {kw_text}")
            else:
                logger.warning("未找到关键词输入框，尝试直接 URL 参数搜索")

            # 尝试定位搜索按钮并点击
            search_btn_selectors = [
                'button[type="submit"]',
                'input[type="submit"]',
                'button:has-text("搜索")',
                'button:has-text("查询")',
                'a:has-text("搜索")',
                '[class*="search-btn"]',
                '[class*="searchBtn"]',
            ]

            clicked = False
            for sel in search_btn_selectors:
                try:
                    btn = page.query_selector(sel)
                    if btn and btn.is_visible():
                        btn.click()
                        clicked = True
                        logger.debug("已点击搜索按钮")
                        break
                except Exception:
                    continue

            if not clicked and keyword_input:
                # 尝试按回车
                keyword_input.press("Enter")
                logger.debug("已按回车提交搜索")

            # 等待结果加载
            random_sleep(2, 4)
            page.wait_for_load_state("networkidle", timeout=30000)
        except Exception as e:
            logger.warning(f"搜索操作异常: {e}")

    def _parse_result_list(self, page) -> List[dict]:
        """
        解析搜索结果列表（三级提取：CSS → LLM → 空）。
        返回标题和链接列表。
        """
        try:
            # 站点适配器优先：命中则使用站点专用解析
            if self.adapter:
                adapter_items = self.adapter.parse_result_list(page)
                if adapter_items:
                    logger.info(f"[{self.config.site_name}] 适配器解析到 {len(adapter_items)} 条列表结果")
                    return adapter_items
                logger.info(f"[{self.config.site_name}] 适配器未解析到结果，降级通用解析")

            # 第一级：通用 CSS/JS 选择器提取
            links = page.evaluate("""() => {
                const results = [];
                const selectors = [
                    // 通用招标网站选择器
                    'table tbody tr a',
                    '.result-list a',
                    '.list-item a',
                    '.search-result a',
                    'ul.list a',
                    '.article-list a',
                    // ccgp.gov.cn 专用：ul class 包含 result-list-bid
                    'ul[class*="result-list-bid"] li a',
                    'ul[class*="result-list"] li a',
                    '.vT-srch-result-list a',
                    // 通用：任何包含 "result" 的 ul 下的 li a
                    'ul[class*="result"] li a',
                ];
                const seen = new Set();
                for (const sel of selectors) {
                    try {
                        const els = document.querySelectorAll(sel);
                        for (const el of els) {
                            const href = el.href;
                            const text = el.textContent.trim();
                            if (href && text && text.length > 5 && !seen.has(href)) {
                                seen.add(href);
                                results.push({title: text, url: href});
                            }
                        }
                        if (results.length > 0) break;
                    } catch(e) {}
                }
                return results;
            }""")

            links = links if isinstance(links, list) else []
            logger.info(f"CSS 解析到 {len(links)} 条列表结果")

            # 第二级：LLM 降级（CSS 无结果或结果过少时；适配器站点跳过，避免空页浪费调用）
            if (not links or len(links) < 3) and settings.llm_enabled and not self.adapter:
                if not links:
                    logger.info("CSS 选择器未匹配到结果，降级到 AI 分析模式...")
                else:
                    logger.info(f"CSS 仅匹配到 {len(links)} 条，尝试 AI 补充分析...")
                html = page.content()
                # 保存调试 HTML 以便排查
                self._save_debug_html(html, page.url, f"list_{len(links)}items")
                ai_links = self.extractor.extract_from_html(
                    html, page.url, self.extractor.DEFAULT_LIST_INSTRUCTION
                )
                logger.info(f"AI 解析到 {len(ai_links)} 条列表结果")
                if ai_links and len(ai_links) > len(links):
                    links = ai_links  # AI 结果更多，使用 AI

            return links
        except Exception as e:
            logger.warning(f"解析结果列表失败: {e}")
            return []

    def _save_debug_html(self, html: str, url: str = "", tag: str = ""):
        """保存调试 HTML 到 data/debug/ 目录"""
        from pathlib import Path
        from hashlib import md5
        from datetime import datetime
        debug_dir = Path("data/debug")
        debug_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        url_hash = md5(url.encode()).hexdigest()[:8] if url else "unknown"
        filename = f"parse_{tag}_{ts}_{url_hash}.html"
        path = debug_dir / filename
        path.write_text(html, encoding="utf-8", errors="replace")
        logger.info(f"调试 HTML 已保存: {path}")

    def _fetch_details(self, page, context, items: List[dict]):
        """逐条打开详情页并提取信息"""
        login_prompted = False  # 避免重复提示

        for item in items:
            # 总时长上限：到了就停止抓取详情，避免后台任务无限运行
            if self._is_expired():
                logger.warning(
                    f"[{self.config.site_name}] 已达单次任务时长上限 "
                    f"({settings.CRAWL_MAX_SECONDS}s)，提前结束详情抓取"
                )
                break
            detail_url = item.get("url", "")
            title = item.get("title", "")
            if not detail_url:
                continue

            # 适配器标记的完整条目：列表已含全文，无需再开详情页
            if item.get("complete"):
                hash_val = url_hash(detail_url)
                if any(r.url_hash == hash_val for r in self.results):
                    continue
                result = CrawlResult(
                    url=detail_url,
                    title=title,
                    item_type=self.config.search_type,
                )
                result.publish_date = item.get("publish_date", "")
                result.amount = item.get("amount", "")
                result.source_org = item.get("source_org", "")
                result.detail_text = item.get("detail_text", "")
                result.keywords_matched = self._current_keyword
                self.results.append(result)
                logger.debug(f"适配器完整条目入库: {title[:40]}")
                continue

            try:
                # 检查是否已有此 URL
                hash_val = url_hash(detail_url)
                if any(r.url_hash == hash_val for r in self.results):
                    continue

                # 新标签页打开详情
                if context:
                    detail_page = context.new_page()
                else:
                    detail_page = page.context.new_page()

                detail_page.goto(detail_url, timeout=30000)
                random_delay(2, 8)
                self._wait_settled(detail_page, timeout_ms=15000)

                # 检测是否需要微信/扫码登录
                if not login_prompted and self._detect_login_page(detail_page):
                    login_prompted = True
                    if self._handle_detail_login(detail_page, context):
                        # 登录成功后，重新加载详情页
                        detail_page.goto(detail_url, timeout=30000)
                        random_delay(1, 3)
                        detail_page.wait_for_load_state("networkidle", timeout=15000)

                html = detail_page.content()

                # 提取内容（使用详情页专用指令）
                extracted = self.extractor.extract(
                    html=html, url=detail_url,
                    instruction=self.extractor.DEFAULT_DETAIL_INSTRUCTION,
                )
                if extracted:
                    for ex in extracted:
                        result = CrawlResult(
                            url=detail_url,
                            title=ex.get("title", title),
                            item_type=self.config.search_type,
                        )
                        result.publish_date = ex.get("publish_date", "")
                        result.amount = ex.get("amount", "")
                        result.source_org = ex.get("source_org", "")
                        result.detail_text = ex.get("content_summary", "")
                        result.keywords_matched = self._current_keyword
                        self.results.append(result)
                else:
                    # 即使提取为空，也记录基础信息
                    result = CrawlResult(
                        url=detail_url,
                        title=title,
                        item_type=self.config.search_type,
                    )
                    result.keywords_matched = self._current_keyword
                    self.results.append(result)

                detail_page.close()
            except Exception as e:
                logger.warning(f"详情页抓取失败 {detail_url}: {e}")
                try:
                    detail_page.close()
                except Exception:
                    pass

    def _go_next_page(self, page) -> bool:
        """尝试翻到下一页，返回是否成功"""
        try:
            next_selectors = [
                'a:has-text("下一页")',
                'a:has-text("下页")',
                'a:has-text(">")',
                'a:has-text("»")',
                '[class*="next"]',
                '.pagination .next',
            ]

            for sel in next_selectors:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    random_sleep(1, 3)
                    page.wait_for_load_state("networkidle", timeout=15000)
                    logger.debug("已翻到下一页")
                    return True
            return False
        except Exception:
            return False

    def _try_api_search(self, page, keyword: str) -> bool:
        """
        Task 4: API 拦截式搜索。
        当 SPA 搜索按钮点击不触发导航/请求时，尝试调用页面内部注册的 API。
        """
        try:
            result = page.evaluate("""async (kw) => {
                // 尝试找 window 上注册的 API 方法
                const apiCalls = [];
                
                // 拦截 fetch
                const origFetch = window.fetch;
                window.fetch = function(...args) {
                    apiCalls.push({url: args[0], options: args[1]});
                    return origFetch.apply(this, args);
                };
                
                // 搜索 search 相关的全局函数
                const searchFns = [];
                for (const key of Object.keys(window)) {
                    if (/search|Search|Ft/.test(key) && typeof window[key] === 'function') {
                        searchFns.push(key);
                    }
                }
                
                // 尝试调用已知的 search API 函数
                // 从 JS bundle 分析: Ft(o) -> POST /website/site/searchAllByCode
                if (typeof window.Ft === 'function') {
                    const resp = await window.Ft({keyword: kw, currentPage: 1, pageSize: 10});
                    return JSON.stringify({method: 'Ft', data: resp});
                }
                
                // 直接在页面 context 中 fetch
                try {
                    const resp = await fetch('/api/website/site/searchAllByCode', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({keyword: kw, keyWord: kw, 
                            currentPage: 1, pageSize: 10})
                    });
                    const text = await resp.text();
                    return JSON.stringify({method: 'fetch', status: resp.status, data: text});
                } catch(e) {
                    return JSON.stringify({method: 'none', searchFns: searchFns, error: e.message});
                }
            }""", keyword)

            data = json.loads(result) if isinstance(result, str) else result
            logger.debug(f"API 拦截结果: {json.dumps(data, ensure_ascii=False)[:200]}")

            # 如果成功获取到数据，解析列表
            inner = data.get("data", data)
            if isinstance(inner, dict):
                data_list = inner.get("data", inner.get("list", inner.get("rows", inner.get("records", []))))
                if isinstance(data_list, list) and data_list:
                    logger.info(f"API 拦截成功，获取到 {len(data_list)} 条数据")
                    for item in data_list:
                        title = item.get("title", item.get("name", item.get("projectName", "")))
                        url = item.get("url", item.get("link", item.get("href", "")))
                        if not url and item.get("id"):
                            # 尝试构造详情 URL
                            url = f"{page.url.rstrip('/')}/detail?id={item.get('id')}"
                        if url:
                            result_obj = CrawlResult(
                                url=url,
                                title=str(title),
                                item_type=self.config.search_type,
                            )
                            result_obj.publish_date = str(item.get("publishDate", item.get("createTime", "")))
                            self.results.append(result_obj)
                    return True
        except Exception as e:
            logger.warning(f"API 拦截搜索失败: {e}")
        return False

    def _handle_captcha(self):
        """Task 6: 验证码检测后的处理"""
        site = self.config.site_name
        logger.warning(f"[{site}] 检测到验证码！")
        if self.no_interact:
            logger.info(f"[{site}] 非交互模式，自动跳过该站点")
            self._blocked = True
            self._mark_site_blocked("验证码要求（非交互模式自动跳过）")
            return
        try:
            choice = input(
                f"\n{'='*60}\n"
                f"站点 [{site}] 要求验证码验证。\n"
                f"请在浏览器中手动完成验证后按 Enter 继续，\n"
                f"或输入 'skip' 跳过此站点，输入 'quit' 退出爬虫。\n"
                f"{'='*60}\n> "
            )
            if choice.lower() == "skip":
                self._blocked = True
                self._mark_site_blocked("验证码要求，用户跳过")
            elif choice.lower() == "quit":
                self._blocked = True
                self._mark_site_blocked("验证码要求，用户退出")
        except (EOFError, KeyboardInterrupt):
            self._blocked = True

    def _handle_auto_verify(self, page) -> bool:
        """
        检测并等待自动安全验证（如 semLogin、JS 挑战）。
        此类验证会自动完成，不需要手动干预。
        优先于 _handle_captcha 执行。

        Returns:
            True 表示自动验证已处理（已等待完成），False 表示未检测到自动验证
        """
        if detect_auto_verify(page):
            site = self.config.site_name
            logger.info(f"[{site}] 检测到自动安全验证，等待自动完成...")
            if wait_for_auto_verify(page, timeout=30):
                logger.info(f"[{site}] 自动安全验证已完成，继续采集")
                return True
            logger.warning(f"[{site}] 自动安全验证等待超时")
        return False

    def _detect_login_page(self, page) -> bool:
        """
        检测详情页是否跳转到了登录/验证页面（如微信扫码登录）。

        Returns:
            True 表示当前页面是登录页
        """
        try:
            url = page.url.lower()
            html = page.content().lower()
            title = page.title().lower()

            login_patterns = [
                ("login", "url"), ("扫描", "text"), ("二维码", "text"),
                ("微信登录", "text"), ("扫码", "text"), ("请登录", "text"),
                ("验证身份", "text"), ("关注公众号", "text"),
                ("semLogin", "url"), ("oauth", "url"), ("authorize", "url"),
            ]

            for pattern, ptype in login_patterns:
                if ptype == "url" and pattern in url:
                    return True
                if ptype == "text" and (pattern in html or pattern in title):
                    return True

            # 检测微信 JS-SDK
            if "res.wx.qq.com" in html:
                return True

        except Exception:
            pass
        return False

    def _handle_detail_login(self, page, context) -> bool:
        """
        处理详情页登录要求。在交互模式下引导用户完成登录后保存会话。

        Returns:
            True 表示登录已完成，False 表示跳过
        """
        site = self.config.site_name
        logger.warning(f"[{site}] 详情页要求登录（微信扫码）")

        if self.no_interact:
            logger.info(f"[{site}] 非交互模式，跳过登录（详情页数据将不完整）")
            return False

        # 有已保存会话但仍然跳到登录页 → 会话可能已过期
        import json
        from pathlib import Path
        session_path = Path("data/browser_sessions") / f"{self.session_name}.json"
        if session_path.exists():
            logger.info(f"[{site}] 已保存的会话可能已过期，需要重新登录")
            session_path.unlink(missing_ok=True)

        try:
            print(f"\n{'='*60}")
            print(f"[{site}] 需要在浏览器中完成微信扫码登录。")
            print(f"请在弹出的浏览器窗口中完成登录后，回到此处按 Enter。")
            print(f"或输入 'skip' 跳过登录（详情页数据将不完整）。")
            print(f"{'='*60}")

            # 在有头浏览器中等待用户登录（page 已可见）
            choice = input("> ").strip()
            if choice.lower() == "skip":
                logger.info(f"[{site}] 用户跳过登录")
                return False

            # 保存登录后的会话状态
            if context:
                from core.browser import BrowserFactory
                BrowserFactory.save_session(context, self.session_name)
                logger.info(f"[{site}] 登录会话已保存，下次不需要重新登录")

            return True

        except (EOFError, KeyboardInterrupt):
            logger.info(f"[{site}] 登录被中断")
            return False

    def _handle_search_noop(self, page):
        """Task 6: 搜索无响应人工介入"""
        site = self.config.site_name
        logger.warning(
            f"[{site}] 搜索可能未生效：URL 和 DOM 均未变化超过 10 秒。\n"
            f"可能原因：反爬拦截、SPA 事件未触发、或搜索表单特殊。\n"
            f"当前页面 URL: {page.url}"
        )
        if self.no_interact:
            logger.info(f"[{site}] 非交互模式，自动跳过该站点")
            self._blocked = True
            self._mark_site_blocked("搜索无响应（非交互模式自动跳过）")
            return
        try:
            choice = input(
                f"\n{'='*60}\n"
                f"站点 [{site}] 搜索未生效。\n"
                f"请在浏览器中手动完成搜索后按 Enter 继续爬取，\n"
                f"或输入 'skip' 跳过此站点，输入 'quit' 退出。\n"
                f"{'='*60}\n> "
            )
            if choice.lower() == "skip":
                self._blocked = True
                self._mark_site_blocked("搜索未响应，用户跳过")
            elif choice.lower() == "quit":
                self._blocked = True
                self._mark_site_blocked("搜索未响应，用户退出")
        except (EOFError, KeyboardInterrupt):
            self._blocked = True

    def _mark_site_blocked(self, reason: str):
        """Task 5/6: 标记站点受阻，写入 data/blocked_sites.json"""
        from pathlib import Path
        from datetime import datetime

        blocked_file = Path("data/blocked_sites.json")
        blocked_file.parent.mkdir(parents=True, exist_ok=True)

        entry = {
            "site_name": self.config.site_name,
            "site_url": self.config.site_url,
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
        }

        records = []
        if blocked_file.exists():
            try:
                records = json.loads(blocked_file.read_text(encoding="utf-8"))
            except Exception:
                records = []

        # 去重
        records = [r for r in records if r.get("site_name") != self.config.site_name]
        records.append(entry)
        blocked_file.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"站点 [{self.config.site_name}] 已记录到受阻列表: {reason}")

    def _cleanup(self, driver, browser, context):
        """清理浏览器资源"""
        try:
            if context:
                context.close()
            if browser:
                browser.close()
            if driver:
                driver.stop()
        except Exception:
            pass
