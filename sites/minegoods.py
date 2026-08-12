"""山东能源集团招标投标交易平台适配器（minegoods 系）。

站点特点：
  - 服务端渲染，关键词搜索 URL：/sdnycms/category/bulletinList.html?word={keyword}&categoryId=2&page=1
  - 列表条目含标题(h1)、日期(.newsDate)、招标编号/方式等；
  - 详情页正文需登录（标题可见），列表级信息入库即可。
"""

import re
import urllib.parse
from typing import List

from sites.base import BaseSiteAdapter


class MineGoodsSiteAdapter(BaseSiteAdapter):
    SITE_NAMES = ("山东能源集团招标投标交易平台",)

    @classmethod
    def matches(cls, site_name: str) -> bool:
        return any(n in site_name for n in cls.SITE_NAMES)

    def get_search_url(self, keyword: str) -> str:
        base = self.config.site_url.rstrip("/")
        return (
            f"{base}/sdnycms/category/bulletinList.html"
            f"?word={urllib.parse.quote(keyword)}&categoryId=2&page=1"
        )

    def parse_result_list(self, page) -> List[dict]:
        # 用当前页面 URL 推导站点原点
        parts = page.url.split("/")
        origin = f"{parts[0]}//{parts[2]}"
        items = page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll('a[href*="sdny_bulletin"]').forEach(a => {
                    const title = ((a.getAttribute('title') || a.querySelector('h1')?.textContent || ''))
                        .trim().replace(/\\s+/g, ' ');
                    const dateEl = a.querySelector('.newsDate div');
                    const href = a.getAttribute('href') || '';
                    if (title.length > 4 && href) {
                        out.push({
                            title: title,
                            url: href,
                            date: dateEl ? dateEl.textContent.trim() : ''
                        });
                    }
                });
                return out;
            }"""
        )
        results = []
        for it in items or []:
            url = it.get("url", "")
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = origin + url
            results.append({
                "title": it.get("title", ""),
                "url": url,
                "publish_date": self._norm_date(it.get("date", "")),
                "complete": True,  # 详情正文需登录，列表级信息入库
            })
        return results

    @staticmethod
    def _norm_date(date: str) -> str:
        m = re.match(r"\s*(\d{4})-(\d{1,2})-(\d{1,2})", date or "")
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return (date or "").strip()
