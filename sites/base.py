"""
站点爬虫基类
每个招标站点的适配器继承此基类，实现定制化的搜索/解析逻辑。
"""
from typing import List
from utils.excel_reader import SiteConfig


class BaseSiteAdapter:
    """
    站点适配器基类。

    每个站点可以继承此类，覆盖以下方法以适配特定站点的 HTML 结构：
    - get_search_url: 构造搜索 URL（适用于 GET 方式）
    - fill_search_form: 填写搜索表单（适用于 POST 方式）
    - parse_result_list: 解析搜索结果列表
    - parse_detail_page: 解析详情页
    """

    # 站点名称（与 Excel 中 site_name 匹配）
    site_name: str = ""
    # 是否支持按关键词搜索（False 表示站点无关键词搜索，爬虫单遍采集、适配器本地过滤）
    MULTI_KEYWORD_SEARCH: bool = True

    def __init__(self, config: SiteConfig):
        self.config = config

    def get_search_url(self) -> str:
        """
        构造搜索 URL。
        默认直接使用 Excel 中的 site_url。
        覆盖此方法可拼接 GET 参数。
        """
        return self.config.site_url

    def after_search(self, page, keyword: str = "") -> None:
        """搜索页加载完成后调用（如点击排序/时间筛选/输入二次搜索等），默认无操作。

        Args:
            page: Playwright page 对象
            keyword: 当前正在搜索的关键词（多关键词站点可用于页面内二次搜索）
        """
        return None

    def fill_search_form(self, page) -> bool:
        """
        填写搜索表单。
        默认返回 False 表示使用通用逻辑。

        覆盖此方法可实现站点专用的表单填写逻辑。

        Args:
            page: Playwright/Playwright-compatible page 对象

        Returns:
            True 表示已处理，使用通用逻辑
        """
        return False

    def parse_result_list(self, page) -> List[dict]:
        """
        解析搜索结果列表。

        覆盖此方法可实现站点专用的列表解析。

        Args:
            page: Playwright/Playwright-compatible page 对象

        Returns:
            结果列表 [{"title": "...", "url": "..."}, ...]
        """
        return []

    def parse_detail_page(self, html: str) -> dict:
        """
        解析详情页。

        覆盖此方法可实现站点专用的详情提取。

        Args:
            html: 详情页 HTML 内容

        Returns:
            提取的字段字典 {"title": "...", "publish_date": "...", ...}
        """
        return {}

    @classmethod
    def matches(cls, site_name: str) -> bool:
        """检查是否匹配该站点"""
        return cls.site_name and cls.site_name in site_name
