"""
通用工具函数
"""
import hashlib
import random
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional
from loguru import logger


def url_hash(url: str) -> str:
    """对 URL 做 SHA256 哈希，用于去重"""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def is_valid_url(url: str) -> bool:
    """粗略校验 URL 是否为可导航的 http(s) 绝对地址，兼容含 {keyword} 占位符的模板。"""
    from urllib.parse import urlparse

    if not url or not isinstance(url, str):
        return False
    s = url.strip()
    if not s or len(s) > 2048:
        return False
    parsed = urlparse(s)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def random_sleep(min_sec: float = 2.0, max_sec: float = 10.0):
    """随机等待，模拟人类操作间隔"""
    delay = random.uniform(min_sec, max_sec)
    logger.debug(f"随机等待 {delay:.1f}s")
    time.sleep(delay)


def days_ago_to_date(days: int) -> str:
    """
    将"距今天数"转换为日期字符串。

    Args:
        days: 距今天的天数，如 5 表示 5 天前

    Returns:
        YYYY-MM-DD 格式的日期字符串
    """
    return (date.today() - timedelta(days=days)).isoformat()


def ensure_dir(path: Path):
    """确保目录存在"""
    path.mkdir(parents=True, exist_ok=True)


def truncate_text(text: str, max_len: int = 200) -> str:
    """截断文本"""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def now_iso() -> str:
    """当前时间 ISO 格式字符串"""
    return datetime.now().isoformat()
