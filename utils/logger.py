"""
日志系统配置
基于 loguru，提供控制台 + 文件双输出，按日轮转。
"""
import sys
from pathlib import Path
from loguru import logger

# 移除默认 handler
logger.remove()

# 控制台输出格式
CONSOLE_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)

# 文件输出格式
FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
    "{level: <8} | "
    "{name}:{function}:{line} - {message}"
)


def setup_logger(log_dir: Path, level: str = "INFO", retention: str = "30 days"):
    """
    初始化日志系统。

    Args:
        log_dir: 日志文件目录
        level: 日志级别 (DEBUG/INFO/WARNING/ERROR)
        retention: 日志保留时长
    """
    log_dir.mkdir(parents=True, exist_ok=True)

    # 控制台输出
    logger.add(
        sys.stderr,
        format=CONSOLE_FORMAT,
        level=level,
        colorize=True,
        backtrace=True,
        diagnose=True,
    )

    # 全量日志文件（按日轮转）
    logger.add(
        log_dir / "scraper_{time:YYYY-MM-DD}.log",
        format=FILE_FORMAT,
        level="DEBUG",
        rotation="00:00",
        retention=retention,
        compression="gz",
        encoding="utf-8",
        backtrace=True,
        diagnose=True,
    )

    # 错误日志单独文件
    logger.add(
        log_dir / "error_{time:YYYY-MM-DD}.log",
        format=FILE_FORMAT,
        level="ERROR",
        rotation="00:00",
        retention=retention,
        compression="gz",
        encoding="utf-8",
        backtrace=True,
        diagnose=True,
    )

    logger.info(f"日志系统已初始化，日志目录: {log_dir}")
    return logger
