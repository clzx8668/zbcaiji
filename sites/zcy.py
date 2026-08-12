"""政采云系政府采购网适配器（上海、浙江等使用 zcycdn/zcygov 体系的站点）。

特点：
  - 搜索走 SPA 路由 /site/search?k={keyword}&type=1（type=1 搜标题，type=2 搜全文）；
  - 结果列表条目自带完整公告全文（标题/日期/内容），无需逐个打开详情页；
  - 列表级直接入库，减少请求量、降低被限频风险。
"""

import re
import urllib.parse
from typing import List

from sites.base import BaseSiteAdapter


class ZcySiteAdapter(BaseSiteAdapter):
    """政采云系站点适配器"""

    # 站点名包含以下关键字即命中（可扩展）
    SITE_NAMES = ("上海政府采购网", "浙江政府采购网")

    # 金额提取：预算金额 / 中标金额 / 成交金额 / 合同金额 / 最高限价（限制为合理金额格式）
    _AMOUNT_RE = re.compile(
        r"(?:预算金额|中标金额|成交金额|合同金额|最高限价)[^\d]{0,12}"
        r"([1-9]\d{0,11}(?:,\d{3})*(?:\.\d{1,2})?)"
    )

    @classmethod
    def matches(cls, site_name: str) -> bool:
        return any(n in site_name for n in cls.SITE_NAMES)

    def get_search_url(self, keyword: str) -> str:
        """构造搜索 URL：搜标题（type=1）"""
        base = self.config.site_url.rstrip("/")
        return f"{base}/site/search?k={urllib.parse.quote(keyword)}&type=1"

    def parse_result_list(self, page) -> List[dict]:
        """解析搜索结果列表（条目自带全文，标记 complete 跳过详情抓取）"""
        origin = f"{page.url.split('/')[0]}//{page.url.split('/')[2]}"
        items = page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll('.searchResList-content-item').forEach(el => {
                    const a = el.querySelector('a.searchResList-content-itemHref');
                    const t = el.querySelector('.content-itemHref-title');
                    const d = el.querySelector('.content-itemHref-time');
                    const c = el.querySelector('.content-itemHref-content');
                    if (!a || !t) return;
                    const href = a.getAttribute('href');
                    const title = (t.textContent || '').trim().replace(/\\s+/g, ' ');
                    if (!href || title.length < 4) return;
                    out.push({
                        title: title,
                        url: href,
                        publish_date: d ? (d.textContent || '').trim() : '',
                        detail_text: c ? (c.textContent || '').trim().slice(0, 4000) : ''
                    });
                });
                return out;
            }"""
        )

        results = []
        for it in items or []:
            url = it.get("url", "")
            if url.startswith("/"):
                url = origin + url
            date = self._normalize_date(it.get("publish_date", ""))
            text = it.get("detail_text", "")
            results.append({
                "title": it.get("title", ""),
                "url": url,
                "publish_date": date,
                "detail_text": text,
                "amount": self._extract_amount(text),
                "source_org": "",
                "complete": True,  # 列表已含全文，无需再抓详情页
            })
        return results

    @staticmethod
    def _normalize_date(date: str) -> str:
        m = re.match(r"\s*(\d{4})-(\d{1,2})-(\d{1,2})", date or "")
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return (date or "").strip()

    @classmethod
    def _extract_amount(cls, text: str) -> str:
        m = cls._AMOUNT_RE.search(text or "")
        return m.group(1) if m else ""
