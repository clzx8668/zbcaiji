"""政采云系政府采购网适配器（上海、浙江等使用 zcycdn/zcygov 体系的站点）。

采集模式（最科学：浏览器只做签名搜索，详情走直连 HTTP）：
  1. 用浏览器打开 /site/search?k={keyword}&type=1（搜索接口 /portal/all 带 x-sign 签名，无法直连）；
  2. 点击页面"时间筛选"Tab（今日/近3日/近一周/近1月...），让页面自行发出带签名的日期过滤请求；
  3. 解析渲染后的结果列表，收集 articleId；
  4. 详情接口 /portal/detail?articleId=.. 免签名，直接 HTTP 批量拉取完整结构化数据。

站点差异：上海有"近一周"Tab；浙江没有"近一周"，回退"近1月"。
"""

import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

from sites.base import BaseSiteAdapter


class ZcySiteAdapter(BaseSiteAdapter):
    """政采云系站点适配器"""

    SITE_NAMES = ("上海政府采购网", "浙江政府采购网")

    # 按回望天数选择时间 Tab；站点无该 Tab 时依次回退
    TIME_TABS = [
        (3, "近3日"),
        (7, "近一周"),
        (30, "近1月"),
        (90, "近3月"),
        (180, "近半年"),
    ]

    _HTML_TAG_RE = re.compile(r"<[^>]+>")

    @classmethod
    def matches(cls, site_name: str) -> bool:
        return any(n in site_name for n in cls.SITE_NAMES)

    def __init__(self, config):
        super().__init__(config)

    def get_search_url(self, keyword: str) -> str:
        """构造搜索 URL：搜标题（type=1）"""
        base = self.config.site_url.rstrip("/")
        return f"{base}/site/search?k={urllib.parse.quote(keyword)}&type=1"

    def after_search(self, page) -> None:
        """搜索结果页加载后，点击与 days_back 匹配的时间筛选 Tab。
        注意：每个关键词都会重新加载搜索页（Tab 重置为"全部"），因此每次都执行。"""
        days = int(getattr(self.config, "days_back", 7) or 7)
        # 目标 Tab：<=3 近3日，<=7 近一周，<=30 近1月 ...
        want = "全部"
        for limit, label in self.TIME_TABS:
            if days <= limit:
                want = label
                break

        try:
            # 时间 Tab 在 shadow DOM 内，必须用 Playwright locator（可穿透）定位
            tabs = page.locator("[class*='timeItem']")
            tabs.first.wait_for(state="visible", timeout=12000)
            labels = []
            for i in range(tabs.count()):
                try:
                    labels.append((i, tabs.nth(i).inner_text().strip()))
                except Exception:
                    continue
            target_idx = next((i for i, t in labels if t == want), None)
            if target_idx is None:
                target_idx = next((i for i, t in labels if t == "近1月"), None)
            if target_idx is not None:
                tabs.nth(target_idx).click(timeout=8000)
                time.sleep(4)  # 等待带签名的日期过滤请求返回并重渲染
        except Exception:
            pass  # 点击失败则保持默认（全部），不影响后续解析

    def parse_result_list(self, page) -> List[dict]:
        """解析结果列表：DOM 收集 articleId + 直连详情接口补全"""
        origin = f"{page.url.split('/')[0]}//{page.url.split('/')[2]}"
        host = page.url.split("/")[2]
        items = page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll('.searchResList-content-item').forEach(el => {
                    const a = el.querySelector('a.searchResList-content-itemHref');
                    const t = el.querySelector('.content-itemHref-title');
                    const d = el.querySelector('.content-itemHref-time');
                    if (!a || !t) return;
                    const href = a.getAttribute('href');
                    const title = (t.textContent || '').trim().replace(/\\s+/g, ' ');
                    if (!href || title.length < 4) return;
                    const m = href.match(/articleId=([^&]+)/);
                    out.push({
                        title: title,
                        url: href,
                        publish_date: d ? (d.textContent || '').trim() : '',
                        article_id: m ? decodeURIComponent(m[1]) : ''
                    });
                });
                return out;
            }"""
        )

        results = []
        if not items:
            return results

        # 直连详情接口补全（并发 4 线程）
        with ThreadPoolExecutor(max_workers=4) as pool:
            enriched = list(pool.map(lambda it: self._enrich(it, host), items))

        for it, detail in zip(items, enriched):
            url = it.get("url", "")
            if url.startswith("/"):
                url = origin + url
            title = it.get("title", "")
            date = self._normalize_date(detail.get("publish_date") or it.get("publish_date", ""))
            text = detail.get("detail_text", "")
            results.append({
                "title": title,
                "url": url,
                "publish_date": date,
                "detail_text": text,
                "amount": detail.get("amount", ""),
                "source_org": detail.get("source_org", ""),
                "item_type": (
                    "中标公告" if any(k in title for k in ("中标", "成交", "结果", "合同"))
                    else "招标公告"
                ),
                "complete": True,  # 详情已直连补全，无需再开详情页
            })
        return results

    # ── 详情直连 ──

    def _enrich(self, item: dict, host: str) -> dict:
        """直连 /portal/detail 拉取单条详情"""
        article_id = item.get("article_id", "")
        if not article_id:
            return {"detail_text": "", "amount": "", "source_org": ""}
        ts = str(int(time.time() * 1000))
        url = (
            f"https://{host}/portal/detail"
            f"?articleId={urllib.parse.quote(article_id, safe='')}&timestamp={ts}"
        )
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
            "Referer": f"https://{host}/",
        }
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                import json
                data = json.loads(resp.read().decode("utf-8", "ignore"))
            result = data.get("result") or {}
            body = result.get("data") or data.get("data") or {}
            if not isinstance(body, dict):
                body = {}
            content = self._html_to_text(body.get("content") or "")
            amount = self._pick_amount(body, content)
            source_org = (
                body.get("purchaseName")
                or body.get("belongingName")
                or self._extract_source(content)
            )
            publish_date = body.get("publishDate") or ""
            if publish_date and isinstance(publish_date, (int, float)):
                publish_date = time.strftime(
                    "%Y-%m-%d", time.localtime(publish_date / 1000)
                )
            return {
                "detail_text": content[:4000],
                "amount": amount,
                "source_org": str(source_org),
                "publish_date": str(publish_date),
            }
        except Exception:
            return {"detail_text": "", "amount": "", "source_org": "", "publish_date": ""}

    @staticmethod
    def _pick_amount(body: dict, text: str) -> str:
        """优先合同金额，其次预算金额；均无则回退正文正则"""
        for key in ("totalContractAmount", "budgetPrice", "monitorAmount"):
            val = body.get(key)
            if val not in (None, "", "0", 0, "null"):
                return str(val)
        m = re.search(
            r"(?:预算金额|中标金额|成交金额|合同金额|最高限价)[^\d]{0,12}"
            r"([1-9]\d{0,11}(?:,\d{3})*(?:\.\d{1,2})?)",
            text,
        )
        return m.group(1) if m else ""

    @staticmethod
    def _extract_source(text: str) -> str:
        """从公告正文提取采购人/采购单位"""
        for pat in (
            r"采购人（甲方）[：:]\s*([^\s；;，,]{2,40})",
            r"采购人信息[\s\S]{0,40}?名称[：:]\s*([^\s；;，,]{2,40})",
            r"采购人[：:]\s*([^\s；;，,]{2,40})",
            r"采购单位[：:]\s*([^\s；;，,]{2,40})",
            r"招标人[：:]\s*([^\s；;，,]{2,40})",
        ):
            m = re.search(pat, text)
            if m:
                return m.group(1).strip()
        return ""

    @classmethod
    def _html_to_text(cls, html: str) -> str:
        if not html:
            return ""
        text = cls._HTML_TAG_RE.sub(" ", html)
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"&nbsp;?", " ", text)
        return text

    @staticmethod
    def _normalize_date(date: str) -> str:
        m = re.match(r"\s*(\d{4})-(\d{1,2})-(\d{1,2})", date or "")
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return (date or "").strip()
