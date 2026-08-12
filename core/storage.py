"""
SQLite 存储层
负责数据持久化、URL 去重、变更检测。
"""
import sqlite3
from pathlib import Path
from typing import List, Optional
from datetime import datetime
from loguru import logger
from config.settings import settings


class Storage:
    """SQLite 存储管理器"""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        site_name TEXT NOT NULL,
        run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'running',
        items_found INTEGER DEFAULT 0,
        items_new INTEGER DEFAULT 0,
        error_msg TEXT
    );

    CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url_hash TEXT UNIQUE NOT NULL,
        site_name TEXT NOT NULL,
        title TEXT,
        url TEXT NOT NULL,
        publish_date TEXT,
        item_type TEXT,
        keywords_matched TEXT,
        detail_text TEXT,
        amount TEXT,
        source_org TEXT,
        first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        archived INTEGER DEFAULT 0,
        archived_at TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS changes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL REFERENCES items(id),
        changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        field_name TEXT,
        old_value TEXT,
        new_value TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_items_site ON items(site_name);
    CREATE INDEX IF NOT EXISTS idx_items_date ON items(publish_date);
    CREATE INDEX IF NOT EXISTS idx_tasks_site ON tasks(site_name);
    CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.DATABASE_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript(self.SCHEMA)
        logger.debug(f"数据库已就绪: {self.db_path}")

    def create_task(self, site_name: str) -> int:
        """创建爬取任务记录，返回任务 ID"""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO tasks (site_name, status) VALUES (?, 'running')",
                (site_name,)
            )
            return cursor.lastrowid

    def finish_task(self, task_id: int, status: str,
                    items_found: int = 0, items_new: int = 0,
                    error_msg: str = ""):
        """完成爬取任务"""
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE tasks SET status=?, items_found=?, items_new=?,
                   error_msg=? WHERE id=?""",
                (status, items_found, items_new, error_msg, task_id)
            )

    def save_item(self, item_data: dict) -> tuple[bool, bool]:
        """
        保存一条爬取结果。
        自动去重（按 url_hash），检测变更。

        Args:
            item_data: 包含 url_hash, site_name, title, url 等字段的字典

        Returns:
            (is_new, is_changed): 是否新记录，是否有变更
        """
        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT id, title, amount, publish_date, source_org FROM items WHERE url_hash=?",
                (item_data["url_hash"],)
            ).fetchone()

            if existing:
                # 检测变更
                changed_fields = []
                for field in ["title", "amount", "publish_date", "source_org"]:
                    old_val = existing[field] or ""
                    new_val = item_data.get(field, "")
                    if old_val != new_val and new_val:
                        changed_fields.append((field, old_val, new_val))

                if changed_fields:
                    # 记录变更 & 更新
                    for field_name, old_val, new_val in changed_fields:
                        conn.execute(
                            "INSERT INTO changes (item_id, field_name, old_value, new_value) VALUES (?,?,?,?)",
                            (existing["id"], field_name, old_val, new_val)
                        )
                    conn.execute(
                        """UPDATE items SET title=?, amount=?, publish_date=?,
                           source_org=?, detail_text=?, last_updated=CURRENT_TIMESTAMP
                           WHERE id=?""",
                        (
                            item_data.get("title", existing["title"]),
                            item_data.get("amount", existing["amount"]),
                            item_data.get("publish_date", existing["publish_date"]),
                            item_data.get("source_org", existing["source_org"]),
                            item_data.get("detail_text", ""),
                            existing["id"]
                        )
                    )
                    logger.debug(f"更新记录: {item_data.get('title', '')[:30]} ({len(changed_fields)} 个字段变更)")
                    return False, True

                return False, False

            # 新记录
            conn.execute(
                """INSERT INTO items (url_hash, site_name, title, url, publish_date,
                   item_type, keywords_matched, detail_text, amount, source_org)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    item_data["url_hash"],
                    item_data.get("site_name", ""),
                    item_data.get("title", ""),
                    item_data.get("url", ""),
                    item_data.get("publish_date", ""),
                    item_data.get("item_type", ""),
                    item_data.get("keywords_matched", ""),
                    item_data.get("detail_text", ""),
                    item_data.get("amount", ""),
                    item_data.get("source_org", ""),
                )
            )
            logger.debug(f"新增记录: {item_data.get('title', '')[:30]}")
            return True, False

    def query_items(
        self,
        site_name: Optional[str] = None,
        item_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        new_only: bool = False,
        archived: Optional[int] = None,
    ) -> List[dict]:
        """查询爬取结果"""
        conditions = []
        params = []

        if site_name:
            conditions.append("site_name=?")
            params.append(site_name)
        if item_type:
            conditions.append("item_type=?")
            params.append(item_type)
        if date_from:
            conditions.append("publish_date >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("publish_date <= ?")
            params.append(date_to)
        if keyword:
            conditions.append("(title LIKE ? OR detail_text LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        if new_only:
            conditions.append("first_seen >= DATE('now', '-7 days')")
        if archived is not None:
            conditions.append("archived=?")
            params.append(archived)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        sql = f"SELECT * FROM items {where} ORDER BY first_seen DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def get_stats(self, days: int = 7) -> dict:
        """获取统计信息（仅统计未归档记录）"""
        with self._get_conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM items WHERE archived=0").fetchone()[0]
            recent = conn.execute(
                "SELECT COUNT(*) FROM items WHERE archived=0 AND first_seen >= DATE('now', ?)",
                (f"-{days} days",)
            ).fetchone()[0]
            by_site = conn.execute(
                "SELECT site_name, COUNT(*) as cnt FROM items WHERE archived=0 GROUP BY site_name ORDER BY cnt DESC"
            ).fetchall()
            by_type = conn.execute(
                "SELECT item_type, COUNT(*) as cnt FROM items WHERE archived=0 GROUP BY item_type"
            ).fetchall()

            return {
                "total_items": total,
                "recent_items": recent,
                "by_site": [dict(r) for r in by_site],
                "by_type": [dict(r) for r in by_type],
            }
