"""中国石化物资采购电子商务平台适配器。

站点特点：
  - 首页即"最新招标公告"流（约 70 条，含日期），无公开关键词搜索；
  - 详情页需供应商登录（未登录重定向回首页），只能取列表级标题/日期/链接；
  - 采集策略：单遍拉取首页公告流，本地按关键词过滤。
"""

import re
from typing import List

from sites.base import BaseSiteAdapter


class SinopecSiteAdapter(BaseSiteAdapter):
    SITE_NAMES = ("中国石化电子招投标平台",)
    MULTI_KEYWORD_SEARCH = False  # 无关键词搜索，首页全量流 + 本地过滤

    @classmethod
    def matches(cls, site_name: str) -> bool:
        return any(n in site_name for n in cls.SITE_NAMES)

    def get_search_url(self, keyword: str = "") -> str:
        return self.config.site_url.rstrip("/") + "/"

    def parse_result_list(self, page) -> List[dict]:
        keywords = self.config.keywords or []
        origin = self.config.site_url.rstrip("/")
        items = page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll('a[href*="bidNotice.do"]').forEach(a => {
                    const item = a.closest('.itemli');
                    const title = (a.textContent || '').trim().replace(/\\s+/g, ' ');
                    const dateEl = item ? item.querySelector('.date') : null;
                    const date = dateEl ? (dateEl.textContent || '').trim() : '';
                    const href = a.getAttribute('href') || '';
                    if (title.length > 4 && href) out.push({title, url: href, date});
                });
                return out;
            }"""
        )
        results = []
        for it in items or []:
            title = it.get("title", "")
            matched = next((k for k in keywords if k and k in title), "")
            if not matched:
                continue
            url = it.get("url", "")
            if url.startswith("/"):
                url = origin + url
            results.append({
                "title": title,
                "url": url,
                "publish_date": self._norm_date(it.get("date", "")),
                "keywords_matched": matched,
                "complete": True,  # 详情需登录，列表级信息入库
            })
        return results

    @staticmethod
    def _norm_date(date: str) -> str:
        m = re.match(r"\s*(\d{4})/(\d{1,2})/(\d{1,2})", date or "")
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return (date or "").strip()
