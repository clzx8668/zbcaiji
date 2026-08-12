"""中海油采办业务管理与交易系统适配器。

站点现状（2026-08 实测）：
  - 旧站 buy.cnooc.com.cn 已故障（302 到 /50x.html 死循环），内容已迁移到
    供应链数字化平台 bid.cnooc.com.cn；
  - 新平台 HTML 偶发 502，但 REST API 稳定（无需登录、无需会话 Cookie）；
  - 公告列表 API 支持 columnId + 日期范围分页，每页固定 10 条；
  - 关键词搜索参数 title 不稳定（时好时坏），因此采用"日期范围全量拉取 +
    本地关键词过滤"策略，稳定且不依赖站点搜索；
  - 详情 API 返回完整正文（HTML），适配器负责清洗为纯文本。

采集模式：MULTI_KEYWORD_SEARCH=False，单遍采集，适配器内部过滤。
"""

import datetime as dt
import json
import re
import time
import urllib.parse
import urllib.request
from typing import List

from sites.base import BaseSiteAdapter

API_BASE = (
    "https://bid.cnooc.com.cn/prodeta/homeportalweb/portal/"
    "indexHome/background"
)
LIST_API = API_BASE + "/businessannouncement/page"
DETAIL_API = API_BASE + "/businessannouncement/detail/"
FRONTEND_URL = "https://bid.cnooc.com.cn/home/#/newsAlertDetails?id="

# 招标采购栏目 ID（栏目树中"招标采购"根节点）
COLUMN_ID = "21"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://bid.cnooc.com.cn/home/#/navigation",
    "Accept": "application/json, text/plain, */*",
}

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_STYLE_SCRIPT_RE = re.compile(
    r"<(style|script)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL
)
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)


class CnoocSiteAdapter(BaseSiteAdapter):
    """中海油新平台（供应链数字化平台）适配器"""

    SITE_NAMES = ("中海油采办业务管理与交易系统",)
    MULTI_KEYWORD_SEARCH = False  # 关键词搜索不稳定，日期范围全量 + 本地过滤

    @classmethod
    def matches(cls, site_name: str) -> bool:
        return any(n in site_name for n in cls.SITE_NAMES)

    def get_search_url(self, keyword: str = "") -> str:
        """直接导航到列表 API（JSON），避免站点 HTML 502 导致 goto 失败。"""
        q = urllib.parse.urlencode(
            {
                "current": 1,
                "size": 10,
                "pageNum": 1,
                "pageSize": 10,
                "page": 1,
                "columnId": COLUMN_ID,
                "status": 3,
            }
        )
        return f"{LIST_API}?{q}"

    def parse_result_list(self, page) -> List[dict]:
        days = max(1, int(getattr(self.config, "days_back", 1) or 1))
        now = dt.datetime.now()
        start = now - dt.timedelta(days=days)
        start_s = start.strftime("%Y-%m-%d 00:00:00")
        end_s = now.strftime("%Y-%m-%d %H:%M:%S")
        keywords = self.config.keywords or []

        first = self._get_list(1, start_s, end_s)
        result = first.get("result") or {}
        total = result.get("total") or 0
        pages = max(1, result.get("pages") or 0)
        if not total:
            return []

        candidates = list(result.get("data") or [])
        for cur in range(2, pages + 1):
            data = self._get_list(cur, start_s, end_s)
            candidates.extend((data.get("result") or {}).get("data") or [])
            time.sleep(0.5)  # 低频率礼貌延迟

        results = []
        for it in candidates:
            title = (it.get("title") or "").strip()
            if len(title) < 4:
                continue
            matched = next((k for k in keywords if k and k in title), "")
            if not matched:
                continue
            item_id = str(it.get("id") or "")
            detail_text = self._get_detail_text(item_id) if item_id else ""
            results.append({
                "title": title,
                "url": f"{FRONTEND_URL}{urllib.parse.quote(item_id, safe='')}",
                "publish_date": str(it.get("createdTime") or "")[:10],
                "detail_text": detail_text[:6000],
                "keywords_matched": matched,
                "item_type": (
                    "中标公告"
                    if any(k in title for k in ("中标", "成交", "结果公告", "异常"))
                    else "招标公告"
                ),
                "complete": True,  # 正文已直连补全
            })
        return results

    # ── HTTP 封装 ──

    def _get_list(self, current: int, start_s: str, end_s: str) -> dict:
        params = {
            "current": current,
            "size": 10,
            "pageNum": current,
            "pageSize": 10,
            "page": current,
            "columnId": COLUMN_ID,
            "status": 3,
            "startDate": start_s,
            "endDate": end_s,
        }
        url = f"{LIST_API}?{urllib.parse.urlencode(params)}"
        return self._get_json(url)

    def _get_detail_text(self, item_id: str) -> str:
        try:
            data = self._get_json(f"{DETAIL_API}{urllib.parse.quote(item_id, safe='')}")
        except Exception:
            return ""
        result = data.get("result") or {}
        full = result.get("fullText") or result.get("content") or ""
        return self._html_to_text(str(full))

    def _get_json(self, url: str, retries: int = 3) -> dict:
        last_err: Exception | None = None
        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, headers=_HEADERS)
                with urllib.request.urlopen(req, timeout=25) as resp:
                    return json.loads(resp.read().decode("utf-8", "ignore"))
            except Exception as e:
                last_err = e
                time.sleep(2 + attempt * 2)
        raise RuntimeError(f"中海油接口请求失败: {url[:100]} ({last_err})")

    @classmethod
    def _html_to_text(cls, html: str) -> str:
        if not html:
            return ""
        # 整页 HTML 时先取 title，正文优先于 CSS 外壳
        title_m = _TITLE_RE.search(html)
        if title_m:
            html = html[title_m.end():]  # 去掉 <head>（含样式），保留正文
        html = _STYLE_SCRIPT_RE.sub(" ", html)
        text = _HTML_TAG_RE.sub(" ", html)
        text = re.sub(r"&nbsp;?", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text
