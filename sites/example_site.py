"""
示例站点适配器
演示如何为特定招标网站编写适配器。
"""
from typing import List
from sites.base import BaseSiteAdapter


class ExampleSiteAdapter(BaseSiteAdapter):
    """
    示例站点适配器。

    实际使用时：
    1. 复制此文件
    2. 设置 site_name 与 Excel 中一致
    3. 覆盖相关方法
    4. 在 sites/__init__.py 中注册
    """

    site_name = "示例站点"

    def get_search_url(self) -> str:
        """构造带 GET 参数的搜索 URL"""
        base_url = self.config.site_url.rstrip("/")
        keywords = "+".join(self.config.keywords)
        return f"{base_url}?keyword={keywords}&type={self.config.search_type}"

    def parse_result_list(self, page) -> List[dict]:
        """
        解析搜索结果列表（示例）

        需要根据实际站点的 HTML 结构调整选择器。
        以下为通用框架，实际使用时替换选择器。
        """
        results = []

        # 示例：假设每个结果在 .search-result-item 中
        items = page.query_selector_all(".search-result-item")

        for item in items:
            try:
                link_el = item.query_selector("a.title")
                date_el = item.query_selector("span.date")

                if link_el:
                    title = link_el.inner_text().strip()
                    url = link_el.get_attribute("href") or ""
                    if title and url:
                        results.append({
                            "title": title,
                            "url": url,
                            "date": date_el.inner_text().strip() if date_el else "",
                        })
            except Exception:
                continue

        return results

    def parse_detail_page(self, html: str) -> dict:
        """
        解析公告详情页（示例）

        需要根据实际站点的详情页结构调整选择器。
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")

        # 示例选择器 - 实际使用时替换
        title_el = soup.select_one("h1.title")
        date_el = soup.select_one("span.publish-date")
        content_el = soup.select_one("div.content")
        amount_el = soup.select_one("span.amount")

        return {
            "title": title_el.get_text(strip=True) if title_el else "",
            "publish_date": date_el.get_text(strip=True) if date_el else "",
            "content_summary": content_el.get_text(strip=True)[:500] if content_el else "",
            "amount": amount_el.get_text(strip=True) if amount_el else "",
            "source_org": "",
        }
