"""
SQLAlchemy 模型 — 映射已有 SQLite 表，不创建新表。
与 core/storage.py 的原始 sqlite3 操作共存。
"""
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class CrawlItem(db.Model):
    __tablename__ = "items"
    __table_args__ = {"extend_existing": True}

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    url_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    site_name = db.Column(db.String(200), nullable=False, index=True)
    title = db.Column(db.String(500))
    url = db.Column(db.String(2000))
    publish_date = db.Column(db.String(50))
    item_type = db.Column(db.String(50))
    keywords_matched = db.Column(db.String(500))
    detail_text = db.Column(db.Text)
    amount = db.Column(db.String(200))
    source_org = db.Column(db.String(500))
    first_seen = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    archived = db.Column(db.Integer, default=0, index=True)
    archived_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f"<CrawlItem {self.title[:40]}>"


class CrawlTask(db.Model):
    __tablename__ = "tasks"
    __table_args__ = {"extend_existing": True}

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    site_name = db.Column(db.String(200), nullable=False, index=True)
    run_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default="running", index=True)
    items_found = db.Column(db.Integer, default=0)
    items_new = db.Column(db.Integer, default=0)
    error_msg = db.Column(db.Text)

    def __repr__(self):
        return f"<CrawlTask {self.site_name} {self.status}>"


class ItemChange(db.Model):
    __tablename__ = "changes"
    __table_args__ = {"extend_existing": True}

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False)
    changed_at = db.Column(db.DateTime, default=datetime.utcnow)
    field_name = db.Column(db.String(100))
    old_value = db.Column(db.Text)
    new_value = db.Column(db.Text)

    item = db.relationship("CrawlItem", backref="changes")

    def __repr__(self):
        return f"<ItemChange item={self.item_id} {self.field_name}>"


class SiteConfigModel(db.Model):
    """站点爬取配置 — 替代 Excel 文件，数据库统一管理"""
    __tablename__ = "site_configs"
    __table_args__ = {"extend_existing": True}

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    site_name = db.Column(db.String(200), unique=True, nullable=False, index=True)
    site_url = db.Column(db.String(500), nullable=False)
    search_type = db.Column(db.String(20), default="both")         # both / zhaobiao / zhongbiao
    keywords = db.Column(db.String(500), default="")                # 逗号分隔
    days_back = db.Column(db.Integer, default=7)
    search_url = db.Column(db.String(2000), default="")
    cron_expr = db.Column(db.String(100), default="0 9 * * *")
    enabled = db.Column(db.Boolean, default=True)
    proxy = db.Column(db.String(500), nullable=True)
    notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<SiteConfig {self.site_name} {'启用' if self.enabled else '禁用'}>"
