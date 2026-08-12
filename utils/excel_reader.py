"""
Excel 模板解析器
读取招标站点配置 Excel，返回结构化配置列表。
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import pandas as pd
from loguru import logger


@dataclass
class SiteConfig:
    """单个站点的爬取配置"""
    site_name: str
    site_url: str  # 站点首页地址
    search_type: str = "both"          # 招标公告 / 中标公告 / both
    keywords: List[str] = field(default_factory=list)
    days_back: int = 7                 # 回溯天数，从今天向前收集多少天
    search_url: str = ""               # 可选：直接指定搜索URL模板，{keyword}/{start_date}/{end_date}
    cron_expr: str = "0 9 * * *"       # 默认每天9点
    enabled: bool = True
    proxy: Optional[str] = None
    notes: str = ""

    @property
    def keywords_str(self) -> str:
        return ", ".join(self.keywords)

    @property
    def date_start(self) -> str:
        """计算实际起始日期（YYYY-MM-DD）"""
        from utils.helpers import days_ago_to_date
        return days_ago_to_date(self.days_back)

    @property
    def date_end(self) -> str:
        """计算实际截止日期（今天）"""
        from datetime import date
        return date.today().isoformat()

    @property
    def date_start_colon(self) -> str:
        """计算实际起始日期（YYYY:MM:DD 格式，如中国政府采购网）"""
        return self.date_start.replace("-", ":")

    @property
    def date_end_colon(self) -> str:
        """计算实际截止日期（YYYY:MM:DD 格式）"""
        return self.date_end.replace("-", ":")


class ExcelReader:
    """Excel 配置读取器"""

    REQUIRED_COLUMNS = ["site_name", "site_url"]
    OPTIONAL_COLUMNS = [
        "search_type", "keywords", "days_back", "search_url",
        "cron_expr", "enabled", "proxy", "notes"
    ]

    COLUMN_ALIASES = {
        # 中文 -> 英文映射
        "站点名称": "site_name",
        "站点地址": "site_url",
        "搜索类型": "search_type",
        "关键词": "keywords",
        "回溯天数": "days_back",
        "搜索URL": "search_url",
        "定时表达式": "cron_expr",
        "是否启用": "enabled",
        "代理": "proxy",
        "备注": "notes",
    }

    def __init__(self, template_path: Path):
        self.template_path = template_path

    def _parse_search_url(self, row) -> str:
        """安全解析 search_url，处理 pandas NaN"""
        val = row.get("search_url", "")
        try:
            if pd.isna(val):
                return ""
        except Exception:
            pass
        s = str(val).strip()
        return "" if s.lower() == "nan" else s

    def _validate_path(self):
        if not self.template_path.exists():
            raise FileNotFoundError(
                f"模板文件不存在: {self.template_path}\n"
                f"请将 Excel 配置模板放在 {self.template_path.parent} 目录下。"
            )

    def read(self) -> List[SiteConfig]:
        """
        读取 Excel 并返回站点配置列表。

        自动识别中英文列名，兼容两种命名风格。
        """
        logger.info(f"正在读取模板: {self.template_path}")

        df = pd.read_excel(self.template_path)

        # 列名规范化（处理中文列名）
        df.rename(columns=self.COLUMN_ALIASES, inplace=True)

        # 校验必填列
        missing = [c for c in self.REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"模板缺少必填列: {missing}")

        configs: List[SiteConfig] = []

        for _, row in df.iterrows():
            # 跳过 enabled=False 的行
            if "enabled" in df.columns:
                enabled_val = row.get("enabled", True)
                if isinstance(enabled_val, str):
                    enabled = enabled_val.strip().lower() in ("true", "1", "yes", "是")
                elif isinstance(enabled_val, (int, float)):
                    enabled = bool(enabled_val)
                else:
                    enabled = True
                if not enabled:
                    logger.info(f"跳过已禁用的站点: {row['site_name']}")
                    continue

            # 解析关键词
            keywords = []
            if "keywords" in df.columns:
                kw = row.get("keywords", "")
                if pd.notna(kw) and str(kw).strip():
                    keywords = [k.strip() for k in str(kw).split(",") if k.strip()]

            # 解析回溯天数
            days_back = 7
            if "days_back" in df.columns:
                dw = row.get("days_back", 7)
                if pd.notna(dw):
                    try:
                        days_back = max(1, int(float(str(dw))))
                    except (ValueError, TypeError):
                        days_back = 7

            config = SiteConfig(
                site_name=str(row["site_name"]).strip(),
                site_url=str(row["site_url"]).strip(),
                search_type=str(row.get("search_type", "both")).strip(),
                keywords=keywords,
                days_back=days_back,
                search_url=self._parse_search_url(row),
                cron_expr=str(row.get("cron_expr", "0 9 * * *")).strip(),
                enabled=True,
                proxy=str(row.get("proxy", "")).strip() or None,
                notes=str(row.get("notes", "")).strip(),
            )
            configs.append(config)

        logger.info(f"成功加载 {len(configs)} 个站点配置")
        return configs

    def create_template(self) -> Path:
        """
        生成一个空模板 Excel 文件。
        只在模板不存在时生成，避免覆盖用户数据。
        """
        if self.template_path.exists():
            logger.info("模板已存在，跳过生成。")
            return self.template_path

        df = pd.DataFrame(columns=[
            "site_name", "site_url", "search_type", "keywords",
            "days_back", "search_url", "cron_expr", "enabled", "proxy", "notes"
        ])

        # 添加示例行
        df.loc[0] = [
            "示例站点",
            "https://example.com/",
            "both",
            "智慧校园,信息化",
            7,
            "",
            "0 9 * * 1-5",
            True,
            "",
            "当搜索URL为空时自动分析首页搜索入口；也可填入完整URL模板如 https://search.xxx.com/bxsearch?kw={keyword}&start_time={start_date}&end_time={end_date}"
        ]

        self.template_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_excel(self.template_path, index=False)
        logger.info(f"模板文件已创建: {self.template_path}")
        return self.template_path
