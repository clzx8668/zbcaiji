"""
全局配置管理
从 .env 文件加载环境变量，提供统一的配置访问接口。
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 项目根目录
ROOT_DIR = Path(__file__).resolve().parent.parent

# 加载 .env
load_dotenv(ROOT_DIR / ".env")


class Settings:
    """全局配置单例"""

    # --- 项目路径 ---
    ROOT_DIR: Path = ROOT_DIR
    DATA_DIR: Path = ROOT_DIR / "data"
    CONFIG_DIR: Path = ROOT_DIR / "config"
    TEMPLATE_PATH: Path = ROOT_DIR / "config" / "template.xlsx"

    # --- LLM 配置 ---
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_API_BASE: str = os.getenv("LLM_API_BASE", "https://api.openai.com/v1")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o-mini")

    @property
    def llm_enabled(self) -> bool:
        return bool(self.LLM_API_KEY)

    # --- 浏览器引擎 ---
    BROWSER_ENGINE: str = os.getenv("BROWSER_ENGINE", "playwright")

    # --- 代理 ---
    HTTP_PROXY: str = os.getenv("HTTP_PROXY", "")
    HTTPS_PROXY: str = os.getenv("HTTPS_PROXY", "")

    # --- 爬取配置 ---
    CRAWL_INTERVAL_MIN: float = float(os.getenv("CRAWL_INTERVAL_MIN", "2"))
    CRAWL_INTERVAL_MAX: float = float(os.getenv("CRAWL_INTERVAL_MAX", "10"))
    CRAWL_TIMEOUT: int = int(os.getenv("CRAWL_TIMEOUT", "120"))
    CRAWL_MAX_SECONDS: int = int(os.getenv("CRAWL_MAX_SECONDS", "900"))
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
    MAX_PAGES: int = int(os.getenv("MAX_PAGES", "5"))

    # --- LLM ---
    LLM_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "30"))

    # --- 搜索分析缓存 ---
    SEARCH_ANALYSIS_CACHE_DIR: Path = DATA_DIR / os.getenv(
        "SEARCH_ANALYSIS_CACHE_DIR", "data/cache/search_analysis"
    ).lstrip("data/")

    # --- 数据库 ---
    DATABASE_PATH: Path = DATA_DIR / os.getenv("DATABASE_PATH", "bid_scraper.db").lstrip("data/")

    # --- 日志 ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_RETENTION: str = os.getenv("LOG_RETENTION", "30 days")
    LOG_DIR: Path = DATA_DIR / "logs"

    # --- 通知 ---
    DINGTALK_WEBHOOK: str = os.getenv("DINGTALK_WEBHOOK", "")
    WECOM_WEBHOOK: str = os.getenv("WECOM_WEBHOOK", "")

    # --- 导出 ---
    OUTPUT_DIR: Path = DATA_DIR / "output"

    def ensure_dirs(self):
        """确保所有必要目录存在"""
        for d in [self.DATA_DIR, self.LOG_DIR, self.OUTPUT_DIR,
                  self.DATA_DIR / "cache", self.SEARCH_ANALYSIS_CACHE_DIR]:
            d.mkdir(parents=True, exist_ok=True)


# 全局配置实例
settings = Settings()
