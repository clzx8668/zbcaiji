"""中国华能集团电子商务平台适配器。

站点特点（2026-08 实测）：
  - 全站（HTML 与 API）受 JS 反爬挑战保护（412 + $_ts 瑞数风格）；
    浏览器必须带 --disable-blink-features=AutomationControlled 启动才能通过；
  - 通过后页面跳到 /channel/home/#/，REST API 在 /scm-uiaoauth-web 下；
  - 采购公告菜单：GET getMenuList?key=zbgg（招标） / key=xjdt（询价等）；
  - 关键词搜索：POST queryAnnouncementByTitle {type, search, start, limit}；
    全文搜索：POST queryAnnouncementByContent（本适配器用标题搜索）；
  - 详情：GET announcementDetail?announcementId=.. 返回 announcementHtml 正文。

采集模式：浏览器驱动（页面自身带反爬 cookie），在页面上下文内 fetch 接口，
每个关键词搜索后分页拉全，并直连详情补全正文。
"""

import json
import re
import time
from typing import List

from sites.base import BaseSiteAdapter

API_PREFIX = "/scm-uiaoauth-web/s/business/uiaouth"
HOME_URL = "https://ec.chng.com.cn/"
FRONTEND_URL = "https://ec.chng.com.cn/channel/home/#/detail?id="


class ChngSiteAdapter(BaseSiteAdapter):
    SITE_NAMES = ("中国华能集团电子商务平台",)

    @classmethod
    def matches(cls, site_name: str) -> bool:
        return any(n in site_name for n in cls.SITE_NAMES)

    def get_search_url(self, keyword: str = "") -> str:
        return HOME_URL

    def after_search(self, page, keyword: str = "") -> None:
        """等待反爬通过，然后按关键词搜索并补全详情，结果存 window。"""
        self._wait_challenge_pass(page)
        items = []
        if keyword:
            items = self._search_keyword(page, keyword)
        page.evaluate(
            """(items) => { window.__chng_items = items || []; }""", items
        )

    def parse_result_list(self, page) -> List[dict]:
        data = page.evaluate("() => window.__chng_items || []")
        page.evaluate("() => { window.__chng_items = []; }")
        results = []
        for it in data or []:
            title = it.get("title") or ""
            if len(title) < 4:
                continue
            results.append({
                "title": title,
                "url": it.get("url", ""),
                "publish_date": it.get("publish_date", ""),
                "detail_text": it.get("detail_text", ""),
                "keywords_matched": it.get("keywords_matched", ""),
                "item_type": it.get("item_type", "招标公告"),
                "complete": True,
            })
        return results

    # ── 反爬挑战 ──

    def _wait_challenge_pass(self, page, attempts: int = 3) -> None:
        for _ in range(attempts):
            deadline = time.time() + 25
            while time.time() < deadline:
                try:
                    url = page.url
                    title = page.title()
                    html_len = len(page.content())
                    if "channel/home" in url and html_len > 1000:
                        return
                except Exception:
                    pass
                time.sleep(2)
            try:
                page.reload(timeout=30000)
            except Exception:
                pass
        raise RuntimeError("华能平台反爬挑战未通过（多次重试失败）")

    # ── 搜索与详情（页面上下文 fetch，自带反爬 cookie） ──

    def _search_keyword(self, page, keyword: str) -> List[dict]:
        # 招标（zbgg）+ 询比/谈判/竞价（xjdt）全部类型，各取最新一页
        types = []
        for key in ("zbgg", "xjdt"):
            menu = self._page_get(page, f"{API_PREFIX}/getMenuList", {"key": key})
            if isinstance(menu, list):
                types.extend(menu)
        if not types:
            types = [{"type": "103"}]

        days = max(1, int(getattr(self.config, "days_back", 7) or 7))
        import datetime as _dt

        cutoff = (_dt.datetime.now() - _dt.timedelta(days=days)).timestamp() * 1000
        items: List[dict] = []
        seen = set()
        for t in types:
            type_id = str(t.get("type") or "")
            if not type_id:
                continue
            data = self._page_post(
                page,
                f"{API_PREFIX}/queryAnnouncementByTitle",
                {"type": type_id, "search": keyword, "start": 0, "limit": 10},
            )
            root = (data or {}).get("root") or []
            for r in root:
                aid = str(r.get("announcementId") or "")
                if not aid or aid in seen:
                    continue
                ts = r.get("createtime")
                if isinstance(ts, (int, float)) and ts < cutoff:
                    continue  # 超出回望窗口，跳过（不再请求详情）
                seen.add(aid)
                title = (r.get("announcementTitle") or "").strip()
                if len(title) < 4:
                    continue
                detail_text = self._fetch_detail(page, aid)
                items.append({
                    "title": title,
                    "url": f"{FRONTEND_URL}{aid}",
                    "publish_date": self._norm_date(ts),
                    "detail_text": detail_text[:6000],
                    "keywords_matched": keyword,
                    "item_type": (
                        "中标公告"
                        if any(k in title for k in ("中标", "成交", "结果"))
                        else "招标公告"
                    ),
                })
            time.sleep(0.3)
        return items

    def _fetch_detail(self, page, announcement_id: str) -> str:
        try:
            data = self._page_get(
                page, f"{API_PREFIX}/announcementDetail", {"announcementId": announcement_id}
            )
            html = (data or {}).get("data", {}).get("announcement", {}).get("announcementHtml") or ""
            return self._html_to_text(str(html))
        except Exception:
            return ""

    # ── 页面 fetch 封装 ──

    def _page_get(self, page, path: str, params: dict) -> dict:
        return page.evaluate(
            """async ({path, params}) => {
                const qs = new URLSearchParams(params || {}).toString();
                const r = await fetch(path + (qs ? '?' + qs : ''), {
                    headers: {'Accept': 'application/json, text/plain, */*'}
                });
                return await r.json();
            }""",
            {"path": path, "params": params},
        )

    def _page_post(self, page, path: str, body: dict) -> dict:
        return page.evaluate(
            """async ({path, body}) => {
                const r = await fetch(path, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json;charset=UTF-8'},
                    body: JSON.stringify(body || {})
                });
                return await r.json();
            }""",
            {"path": path, "body": body},
        )

    # ── 工具 ──

    @staticmethod
    def _norm_date(ts) -> str:
        """时间戳（毫秒）或字符串 -> YYYY-MM-DD"""
        if not ts:
            return ""
        if isinstance(ts, (int, float)):
            import datetime as _dt

            return _dt.datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
        m = re.match(r"\s*(\d{4})-(\d{1,2})-(\d{1,2})", str(ts))
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return str(ts).strip()[:10]

    @staticmethod
    def _html_to_text(html: str) -> str:
        if not html:
            return ""
        html = re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"&nbsp;?", " ", text)
        text = re.sub(r"&#xa0;?", " ", text, flags=re.I)
        text = re.sub(r"&[a-z]+;", " ", text, flags=re.I)
        text = text.replace("preview", "")
        text = re.sub(r"\s+", " ", text).strip()
        return text
