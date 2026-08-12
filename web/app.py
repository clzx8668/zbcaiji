"""
Flask 应用工厂 — 创建并配置 Web 管理后台。
"""
import os
from pathlib import Path
from flask import Flask, redirect, url_for
from dotenv import load_dotenv

# 加载 .env（确保在 config/settings 之前加载）
load_dotenv()

from web.models import db
from web.auth import protect_admin


def create_app(task_manager=None):
    """
    创建 Flask 应用。

    Args:
        task_manager: TaskManager 实例（可选，用于任务管控）
    """
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "bid-scraper-secret-key-change-me")

    # 数据库配置 — 指向已有的 SQLite 数据库
    db_path = os.getenv("DATABASE_PATH", "data/bid_scraper.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{Path(db_path).resolve()}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["FLASK_ADMIN_FLUID_LAYOUT"] = True  # 宽屏布局

    # 确保 data 目录存在
    Path("data/backups").mkdir(parents=True, exist_ok=True)

    db.init_app(app)

    # 自动迁移：确保 site_configs 表存在 + archive 列
    with app.app_context():
        _migrate_site_configs(db)
        _migrate_archive_columns(db)

    # 注入 task_manager 到 app extensions
    if task_manager:
        app.extensions["task_manager"] = task_manager

    # 注册请求日志中间件
    from web.middleware import register_request_logging
    register_request_logging(app)

    # 保护 /admin/* 路径
    protect_admin(app)

    # 注册 Flask-Admin
    with app.app_context():
        from web.admin import setup_admin
        setup_admin(app, db)

    # 注册任务管控 API 蓝图
    from web.views import task_bp, data_bp
    app.register_blueprint(task_bp, url_prefix="/api/task")
    app.register_blueprint(data_bp, url_prefix="/api/data")

    # 根路径重定向到管理后台
    @app.route("/")
    def index():
        return redirect(url_for("admin.index"))

    return app


def _migrate_site_configs(db):
    """
    首次启动时自动创建 site_configs 表，并将 Excel 中的配置迁移到数据库。
    """
    from sqlalchemy import inspect
    from loguru import logger

    engine = db.engine
    inspector = inspect(engine)

    if "site_configs" not in inspector.get_table_names():
        # 表不存在，创建
        from web.models import SiteConfigModel
        SiteConfigModel.__table__.create(engine, checkfirst=True)
        logger.info("已创建 site_configs 表")

        # 尝试从 Excel 导入已有配置
        try:
            from config.settings import settings
            excel_path = settings.TEMPLATE_PATH
            if excel_path.exists():
                from utils.site_config_manager import SiteConfigManager
                mgr = SiteConfigManager()
                result = mgr.import_from_excel(str(excel_path))
                if result["success"] > 0:
                    logger.info(f"已从 Excel 导入 {result['success']} 个站点配置到数据库")
        except Exception as e:
            logger.warning(f"从 Excel 迁移配置失败（可后续手动导入）: {e}")


def _migrate_archive_columns(db):
    """
    为已有 items 表添加 archived / archived_at 列（兼容旧数据库）。
    """
    from sqlalchemy import inspect, text
    from loguru import logger

    engine = db.engine
    inspector = inspect(engine)

    if "items" not in inspector.get_table_names():
        return  # 表不存在则跳过（由 storage.py 首次建表时自动创建）

    columns = {c["name"] for c in inspector.get_columns("items")}
    if "archived" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE items ADD COLUMN archived INTEGER DEFAULT 0"))
        logger.info("已为 items 表添加 archived 列")
    if "archived_at" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE items ADD COLUMN archived_at TIMESTAMP"))
        logger.info("已为 items 表添加 archived_at 列")
