"""
数据库备份模块 — 定时备份 SQLite 数据库文件。
"""
import shutil
import json
from pathlib import Path
from datetime import datetime
from loguru import logger

BACKUP_DIR = Path("data/backups")
DB_PATH = Path("data/bid_scraper.db")
MAX_BACKUPS = 30


def backup_database():
    """
    复制 bid_scraper.db 到 data/backups/，保留最近 30 个备份。
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    if not DB_PATH.exists():
        logger.warning(f"数据库文件不存在，跳过备份: {DB_PATH}")
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"bid_scraper_{timestamp}.db"

    shutil.copy2(DB_PATH, backup_path)
    logger.info(f"数据库已备份: {backup_path}")

    # 清理旧备份
    _cleanup_old_backups()

    return str(backup_path)


def _cleanup_old_backups():
    """保留最近 MAX_BACKUPS 个备份，删除旧的"""
    backups = sorted(BACKUP_DIR.glob("bid_scraper_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[MAX_BACKUPS:]:
        old.unlink()
        logger.debug(f"已删除旧备份: {old.name}")


def list_backups():
    """列出所有备份文件"""
    backups = []
    for f in sorted(BACKUP_DIR.glob("bid_scraper_*.db"), reverse=True):
        stat = f.stat()
        backups.append({
            "name": f.name,
            "path": str(f),
            "size_kb": round(stat.st_size / 1024, 1),
            "created": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return backups


def start_auto_backup():
    """
    启动每天凌晨 2 点的自动备份任务。
    由 Flask app 在启动时调用。
    """
    from apscheduler.schedulers.background import BackgroundScheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        backup_database,
        trigger="cron",
        hour=2,
        minute=0,
        id="auto_backup",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("自动备份任务已启动（每天 02:00）")
    return scheduler
