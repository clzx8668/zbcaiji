"""
智能搜索分析器
自动分析站点首页，发现搜索入口，构造搜索请求。
支持 AI 模式（LLM 分析 DOM）和非 AI 模式（启发式规则）。
"""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List
from loguru import logger
from config.settings import settings
from core.llm_client import get_llm_client


@dataclass
class SearchConfig:
    """搜索入口配置"""
    method: str = "GET"                       # GET / POST / FORM
    search_url_template: str = ""             # 搜索 URL 模板，如 "/search?keyword={keyword}"
    keyword_param: str = "keyword"           # 关键词参数名
    form_selector: str = ""                   # 搜索表单 CSS 选择器
    keyword_field_selector: str = ""          # 关键词输入框 CSS 选择器
    submit_selector: str = ""                 # 提交按钮 CSS 选择器
    date_params: dict = field(default_factory=dict)  # 日期筛选参数
    navigation_link: str = ""                 # 需要点击的搜索入口链接

    @property
    def is_form_based(self) -> bool:
        return self.method in ("POST", "FORM")


class SearchAnalyzer:
    """
    搜索分析器。

    分析流程：
    1. 尝试从缓存加载
    2. AI 模式：提取 DOM 结构 → LLM 分析
    3. 非 AI 模式：启发式规则扫描
    4. 结果缓存
    """

    # LLM 分析 prompt
    ANALYSIS_SYSTEM_PROMPT = """你是一个网页搜索功能分析专家。分析给定的 HTML DOM 结构，找到搜索功能入口。

你需要返回一个 JSON 对象，包含：
{
  "method": "GET" 或 "POST" 或 "FORM",
  "search_url_template": "搜索 URL 模板，如 /search?kw={keyword}，GET 方式时必填",
  "keyword_param": "关键词参数名，如 keyword/kw/q/search",
  "form_selector": "搜索表单的 CSS 选择器（POST/FORM 方式时必填）",
  "keyword_field_selector": "关键词输入框的 CSS 选择器（POST/FORM 方式时必填）",
  "submit_selector": "提交按钮的 CSS 选择器（POST/FORM 方式时必填）",
  "date_params": {"start": "开始日期参数名", "end": "结束日期参数名"},
  "navigation_link": "如果首页没有直接搜索框，但有指向搜索页的链接，填入该链接的 CSS 选择器或 href"
}

注意：
- 如果搜索是通过 GET 方式的 URL 参数，method 填 "GET"
- 如果搜索需要填写表单并提交，method 填 "FORM"
- 只返回 JSON，不要包含其他文字。"""

    def __init__(self):
        self.llm = get_llm_client()
        self.cache_dir = settings.SEARCH_ANALYSIS_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def analyze(self, page, site_name: str, site_url: str = "",
                force: bool = False) -> SearchConfig:
        """
        分析站点首页，发现搜索入口。

        Args:
            page: Playwright page 对象（已加载首页）
            site_name: 站点名称
            site_url: 站点 URL（用于区分同一站点不同 URL 的缓存）
            force: 是否强制重新分析

        Returns:
            SearchConfig 搜索配置
        """
        # 1. 尝试缓存
        if not force:
            cached = self._load_cache(site_name, site_url)
            if cached:
                logger.info(f"[{site_name}] 使用缓存的搜索分析结果")
                return cached

        # 2. AI 分析
        if self.llm.enabled:
            try:
                logger.info(f"[{site_name}] AI 模式分析搜索入口...")
                config = self._analyze_with_ai(page, site_name)
                if config and config.search_url_template:
                    self._save_cache(site_name, config, site_url)
                    return config
            except Exception as e:
                logger.warning(f"[{site_name}] AI 分析失败: {e}，降级到启发式模式")

        # 3. 非 AI 启发式分析
        logger.info(f"[{site_name}] 启发式模式分析搜索入口...")
        config = self._analyze_heuristic(page, site_name)
        self._save_cache(site_name, config, site_url)
        return config

    def _analyze_with_ai(self, page, site_name: str) -> Optional[SearchConfig]:
        """使用 LLM 分析搜索入口"""
        # 提取精简 DOM 结构
        dom_snippet = page.evaluate("""() => {
            const extract = (el, depth = 0) => {
                if (depth > 4) return null;
                const tag = el.tagName ? el.tagName.toLowerCase() : '';
                if (!tag) return null;

                const info = { tag };

                // 关键属性
                const attrs = {};
                for (const attr of ['name', 'id', 'class', 'type', 'placeholder',
                    'action', 'method', 'href', 'onclick', 'onsubmit']) {
                    const val = el.getAttribute(attr);
                    if (val) attrs[attr] = val;
                }
                if (Object.keys(attrs).length > 0) info.attrs = attrs;

                // 可见文本（截断）
                const text = (el.textContent || '').trim();
                if (text && text.length < 100) info.text = text;

                // 子元素
                const children = [];
                for (const child of el.children) {
                    const c = extract(child, depth + 1);
                    if (c) children.push(c);
                }
                if (children.length > 0 && children.length <= 30) {
                    info.children = children;
                }

                return info;
            };

            // 只提取关键区域
            const result = [];
            const forms = document.querySelectorAll('form');
            forms.forEach(f => {
                const info = extract(f);
                if (info) result.push(info);
            });

            // 也提取 input 元素周围的上下文
            const inputs = document.querySelectorAll('input[type="text"], input[type="search"], input:not([type])');
            if (forms.length === 0 && inputs.length > 0) {
                inputs.forEach(inp => {
                    const info = extract(inp, 0);
                    if (info) result.push(info);
                });
            }

            // 提取导航链接中可能指向搜索页的
            const links = document.querySelectorAll('a[href*="search"], a[href*="Search"], a[href*="query"]');
            if (result.length === 0 && links.length > 0) {
                links.forEach(l => {
                    const info = extract(l, 0);
                    if (info) result.push(info);
                });
            }

            return JSON.stringify(result.slice(0, 10));  // 最多10个元素
        }""")

        if not dom_snippet or dom_snippet == "[]":
            logger.warning(f"[{site_name}] 未提取到 DOM 结构")
            return None

        current_url = page.url
        prompt = f"""分析以下网站首页的 DOM 结构，找到搜索功能的入口。

当前页面 URL: {current_url}

DOM 结构:
{dom_snippet[:3000]}"""

        # 调用 LLM
        raw_response = self.llm.chat_completion(
            prompt=prompt,
            system_message=self.ANALYSIS_SYSTEM_PROMPT,
        )

        # 解析 JSON 响应
        data = json.loads(self._extract_json(raw_response))

        method = data.get("method", "GET")
        keyword_field = data.get("keyword_field_selector", "")
        submit_sel = data.get("submit_selector", "")

        # 后处理：如果有关键词输入框，优先用 FORM 方式
        if keyword_field and method == "GET":
            method = "FORM"
            logger.debug(f"[{site_name}] AI 找到了输入框但返回 GET，修正为 FORM")

        return SearchConfig(
            method=method,
            search_url_template=data.get("search_url_template", ""),
            keyword_param=data.get("keyword_param", "keyword"),
            form_selector=data.get("form_selector", ""),
            keyword_field_selector=keyword_field,
            submit_selector=submit_sel,
            date_params=data.get("date_params", {}),
            navigation_link=data.get("navigation_link", ""),
        )

    def _analyze_heuristic(self, page, site_name: str) -> SearchConfig:
        """启发式规则分析搜索入口"""
        base_url = page.url

        # 扫描关键词输入框
        keyword_selectors = [
            'input[name*="keyword"]',
            'input[name*="key"]',
            'input[name*="search"]',
            'input[name*="kw"]',
            'input[name*="q"]',
            'input[placeholder*="关键词"]',
            'input[placeholder*="搜索"]',
            'input[placeholder*="关键字"]',
            'input[id*="keyword"]',
            'input[id*="search"]',
            'input[id*="kw"]',
            'input[class*="search"]',
            'input[type="search"]',
        ]

        keyword_input = None
        keyword_selector = ""

        for sel in keyword_selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    keyword_input = el
                    keyword_selector = sel
                    break
            except Exception:
                continue

        if keyword_input:
            # 找到了输入框，检查是否在 form 内
            form_selector = ""
            submit_selector = ""

            try:
                # 查找附近的 form
                form_in_page = page.evaluate(f"""(sel) => {{
                    const el = document.querySelector(sel);
                    if (!el) return null;
                    const form = el.closest('form');
                    if (!form) return null;
                    // 生成唯一选择器
                    if (form.id) return '#' + form.id;
                    if (form.className) return 'form.' + form.className.split(' ')[0];
                    return 'form';
                }}""", keyword_selector)

                if form_in_page:
                    form_selector = form_in_page

                # 查找提交按钮
                submit_sel = page.evaluate(f"""(sel) => {{
                    const el = document.querySelector(sel);
                    if (!el) return null;
                    const form = el.closest('form');
                    const container = form || document;
                    const btn = container.querySelector('button[type="submit"], input[type="submit"], button:has-text("搜索"), button:has-text("查询")');
                    if (!btn) return null;
                    if (btn.id) return '#' + btn.id;
                    if (btn.className) return 'button.' + btn.className.split(' ')[0];
                    return btn.tagName.toLowerCase();
                }}""", keyword_selector)

                if submit_sel:
                    submit_selector = submit_sel
            except Exception:
                pass

            config = SearchConfig(
                method="FORM",
                keyword_field_selector=keyword_selector,
                form_selector=form_selector,
                submit_selector=submit_selector,
            )
            logger.debug(f"[{site_name}] 启发式: 找到关键词输入框 {keyword_selector}")
            return config

        # 没找到输入框，查找搜索入口链接
        link_selectors = [
            'a:has-text("搜索")',
            'a:has-text("查询")',
            'a:has-text("检索")',
            'a[href*="search"]',
            'a[href*="Search"]',
        ]

        for sel in link_selectors:
            try:
                link = page.query_selector(sel)
                if link and link.is_visible():
                    href = link.get_attribute("href") or ""

                    # 检查是否为 GET 搜索
                    if "?" in href:
                        config = SearchConfig(
                            method="GET",
                            search_url_template=href,
                            keyword_param="keyword",
                        )
                        logger.debug(f"[{site_name}] 启发式: 找到搜索链接 {href}")
                        return config

                    config = SearchConfig(
                        method="LINK",
                        navigation_link=sel,
                    )
                    logger.debug(f"[{site_name}] 启发式: 找到搜索入口链接 {sel}")
                    return config
            except Exception:
                continue

        # 完全找不到，返回默认配置（尝试 URL 搜索）
        logger.warning(f"[{site_name}] 未找到搜索入口，将使用首页 URL 尝试关键词拼接")
        return SearchConfig(
            method="GET",
            search_url_template=base_url.rstrip("/") + "?keyword={keyword}",
            keyword_param="keyword",
        )

    @staticmethod
    def _extract_json(text: str) -> str:
        """从 LLM 响应中提取 JSON 字符串"""
        text = text.strip()
        # 移除 markdown 代码块
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            return text[start:end + 1]
        return text

    def _cache_path(self, site_name: str, site_url: str = "") -> Path:
        """获取缓存文件路径（含 URL hash 避免新旧 URL 冲突）"""
        from hashlib import md5
        safe_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in site_name)
        url_suffix = "_" + md5(site_url.encode()).hexdigest()[:8] if site_url else ""
        return self.cache_dir / f"{safe_name}{url_suffix}.json"

    def _load_cache(self, site_name: str, site_url: str = "") -> Optional[SearchConfig]:
        """加载缓存"""
        cache_file = self._cache_path(site_name, site_url)
        if not cache_file.exists():
            return None
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            return SearchConfig(**data)
        except Exception as e:
            logger.debug(f"缓存读取失败: {e}")
            return None

    def _save_cache(self, site_name: str, config: SearchConfig, site_url: str = ""):
        """保存缓存"""
        cache_file = self._cache_path(site_name, site_url)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "method": config.method,
            "search_url_template": config.search_url_template,
            "keyword_param": config.keyword_param,
            "form_selector": config.form_selector,
            "keyword_field_selector": config.keyword_field_selector,
            "submit_selector": config.submit_selector,
            "date_params": config.date_params,
            "navigation_link": config.navigation_link,
        }
        cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"[{site_name}] 搜索分析结果已缓存")
