"""
日志文件读取工具 — 解析 loguru 的日志文件。
"""
import os
import re
from pathlib import Path
from datetime import datetime

LOG_DIR = Path("data/logs")


def list_log_files():
    """列出所有 scraper 日志文件，按日期倒序"""
    files = []
    if not LOG_DIR.exists():
        return files

    for f in sorted(LOG_DIR.glob("scraper_*.log"), reverse=True):
        stat = f.stat()
        # 提取日期
        date_match = re.search(r"scraper_(\d{4}-\d{2}-\d{2})\.log", f.name)
        date_str = date_match.group(1) if date_match else ""
        files.append({
            "name": f.name,
            "path": str(f),
            "size_kb": round(stat.st_size / 1024, 1),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "date": date_str,
        })

    return files


def read_log(file_path: str, max_lines: int = 500, keyword: str = ""):
    """
    读取日志文件的最后 max_lines 行。
    如果指定 keyword，则筛选包含关键词的行。
    """
    path = Path(file_path)
    if not path.exists():
        return [f"[错误] 日志文件不存在: {file_path}"]

    lines = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fp:
            # 从尾部读取
            if keyword:
                # 带关键词搜索时读取全部内容再过滤
                all_lines = fp.readlines()
                filtered = [l.rstrip() for l in all_lines if keyword.lower() in l.lower()]
                lines = filtered[-max_lines:]
            else:
                # 普通模式 — 只读尾行
                all_lines = fp.readlines()
                lines = [l.rstrip() for l in all_lines[-max_lines:]]
    except Exception as e:
        return [f"[错误] 读取日志失败: {e}"]

    return lines


def download_log(file_path: str) -> tuple:
    """读取日志文件全部内容（用于下载）"""
    path = Path(file_path)
    if not path.exists():
        return None, None

    with open(path, "r", encoding="utf-8", errors="replace") as fp:
        content = fp.read()

    return path.name, content
