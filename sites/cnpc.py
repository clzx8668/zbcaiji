"""中国石油招标投标网适配器。

站点特点（2026-08 实测）：
  - Vue SPA + CMS：所有数据接口请求体由页面 JS 自动 RSA 加密（公钥藏在
    /cms/css/bj.css 的 base64 中），无法脱离浏览器直连构造；
  - 首次访问/新会话需要输入图形验证码（一次性，通过后同会话不再要求）；
  - 列表路由 /#/tenders（招标公告，columnId=1）带"关键字"搜索框与分页；
  - 详情内容同样受验证码 gate 保护，因此采集列表级信息（标题/日期/链接）。

采集模式：浏览器驱动（页面自动处理加密），每个关键词在页面搜索框内搜索。
交互说明：无头/后台模式遇到验证码会直接失败（无法自动通过）；请先用
  python run.py crawl --site "中国石油招标投标网" 交互运行一次，在可见浏览器
  中输入验证码，会话会自动保存，之后一段时间内可跳过验证码。
"""

import re
import time
from typing import List

from sites.base import BaseSiteAdapter


class CnpcSiteAdapter(BaseSiteAdapter):
    SITE_NAMES = ("中国石油招标投标网",)

    @classmethod
    def matches(cls, site_name: str) -> bool:
        return any(n in site_name for n in cls.SITE_NAMES)

    def get_search_url(self, keyword: str = "") -> str:
        """招标公告列表路由（columnId=1）；关键词在页面内搜索框输入。"""
        base = self.config.site_url.rstrip("/")
        return f"{base}/#/tenders"

    def after_search(self, page, keyword: str = "") -> None:
        """搜索页加载后：先处理验证码弹窗，再在页面搜索框输入关键词。"""
        self._handle_captcha_if_needed(page)
        if keyword:
            self._type_keyword_and_search(page, keyword)

    # ── 验证码 ──

    def _handle_captcha_if_needed(self, page) -> None:
        """检测"输入验证码"弹窗：交互模式引导用户输入，无头模式直接失败。"""
        # 验证码弹窗在页面加载约 8~15s 后才出现；若列表已渲染则无需验证码
        deadline = time.time() + 15
        dialog = None
        while time.time() < deadline:
            try:
                if page.locator(".box_data.cursor_style").first.is_visible():
                    return  # 列表已出现，无需验证码
            except Exception:
                pass
            try:
                cand = page.locator(".el-dialog__wrapper").all()
                for d in cand:
                    if d.is_visible() and "验证码" in ((d.inner_text() or "")[:60]):
                        dialog = d
                        break
            except Exception:
                pass
            if dialog:
                break
            time.sleep(1)

        if dialog is None:
            return  # 15s 内无验证码弹窗

        # 有验证码：交互模式等待用户输入，无头/后台模式失败
        try:
            input(
                "\n" + "=" * 60 + "\n"
                "站点 [中国石油招标投标网] 需要输入图形验证码。\n"
                "请在浏览器弹窗中输入验证码并点击【提交】，\n"
                "完成后回到此处按 Enter 继续。\n"
                "（输入 skip 可跳过本站点）\n"
                + "=" * 60 + "\n> "
            )
        except EOFError:
            raise RuntimeError(
                "中石油站点需要人工输入图形验证码；请在交互模式运行一次"
                "（python run.py crawl --site \"中国石油招标投标网\"）"
            )

        # 等待验证码弹窗关闭（用户提交成功后页面自动重新加载列表）
        deadline = time.time() + 90
        while time.time() < deadline:
            try:
                visible = False
                for d in page.locator(".el-dialog__wrapper").all():
                    try:
                        if d.is_visible() and "验证码" in ((d.inner_text() or "")[:60]):
                            visible = True
                            break
                    except Exception:
                        continue
                if not visible:
                    return
            except Exception:
                return
            time.sleep(2)
        raise RuntimeError("等待中石油验证码提交超时（90s）")

    # ── 页面内搜索 ──

    def _type_keyword_and_search(self, page, keyword: str) -> None:
        """在列表页"关键字"输入框填入关键词并点击搜索。"""
        try:
            box = page.locator('input[placeholder="请输入"]').first
            box.wait_for(state="visible", timeout=8000)
            box.fill(keyword)
        except Exception:
            return  # 找不到搜索框则保持默认列表，由解析层本地过滤

        try:
            btn = page.locator("button.search, button:has-text('搜索')").first
            btn.click(timeout=5000)
        except Exception:
            try:
                box.press("Enter")
            except Exception:
                pass
        time.sleep(4)  # 等待加密请求返回并重渲染

    # ── 列表解析 ──

    def parse_result_list(self, page) -> List[dict]:
        try:
            page.locator(".box_data.cursor_style").first.wait_for(
                state="visible", timeout=8000
            )
        except Exception:
            return []

        data = page.evaluate(
            """() => {
                const rows = document.querySelectorAll('.box_data.cursor_style');
                const vm = rows[0] && rows[0].__vue__;
                const list = (vm && vm.list) || [];
                const out = [];
                rows.forEach((el, i) => {
                    const title = (el.querySelector('.contant') || {}).textContent || '';
                    const dateEl = el.querySelectorAll('div')[1];
                    const id = (list[i] && list[i].id) || '';
                    out.push({
                        title: title.trim().replace(/\\s+/g, ' '),
                        date: dateEl ? (dateEl.textContent || '').trim() : '',
                        id: String(id)
                    });
                });
                return out;
            }"""
        )

        keywords = self.config.keywords or []
        results = []
        for it in data or []:
            title = it.get("title", "")
            if len(title) < 4:
                continue
            matched = next((k for k in keywords if k and k in title), "")
            if not matched:
                continue
            item_id = it.get("id", "")
            url = f"https://www.cnpcbidding.com/#/details/{item_id}" if item_id else ""
            results.append({
                "title": title,
                "url": url,
                "publish_date": self._norm_date(it.get("date", "")),
                "keywords_matched": matched,
                "complete": True,  # 详情需过验证码/登录，列表级信息入库
            })
        return results

    @staticmethod
    def _norm_date(date: str) -> str:
        m = re.match(r"\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})", date or "")
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return (date or "").strip()
