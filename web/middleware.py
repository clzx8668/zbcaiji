"""
请求日志中间件 — 记录所有 API 请求到 web_access.log。
"""
import logging
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler
from flask import request


def register_request_logging(app):
    """注册请求日志中间件到 Flask app"""
    log_dir = Path("data/logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    # 创建专用的 web_access logger
    access_logger = logging.getLogger("web_access")
    access_logger.setLevel(logging.INFO)
    access_logger.propagate = False

    # 避免重复添加 handler
    if not access_logger.handlers:
        handler = TimedRotatingFileHandler(
            filename=str(log_dir / "web_access.log"),
            when="W0",            # 每周一 0 点轮转
            interval=1,
            backupCount=4,        # 保留 4 周
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        access_logger.addHandler(handler)

    @app.before_request
    def log_request():
        # 跳过静态资源
        if request.path.startswith("/static") or request.path.startswith("/admin/static"):
            return

        access_logger.info(
            f"{request.remote_addr} | {request.method} {request.path} | "
            f"UA: {request.headers.get('User-Agent', '?')[:80]}"
        )

    @app.after_request
    def log_response(response):
        if not request.path.startswith("/static") and not request.path.startswith("/admin/static"):
            access_logger.info(
                f"{request.remote_addr} | -> {response.status_code} {request.method} {request.path}"
            )
        return response
