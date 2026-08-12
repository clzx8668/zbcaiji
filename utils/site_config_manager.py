"""
站点配置管理器 — 从数据库统一读取/管理站点爬取配置。
替代原有的 ExcelReader 直接读取 Excel 方式。
"""
import json
import sqlite3
from pathlib import Path
from typing import List, Optional
from loguru import logger
from utils.excel_reader import SiteConfig


DB_PATH = Path("data/bid_scraper.db")


class SiteConfigManager:
    """
    站点配置管理器，所有站点信息的唯一读写入口。

    用法:
        mgr = SiteConfigManager()
        configs = mgr.get_all(enabled_only=True)
        mgr.save(site_name="xxx", site_url="https://...", keywords="智慧校园")
        mgr.delete(site_name="xxx")
        result = mgr.import_from_excel("import.xlsx")
    """

    def __init__(self, db_path: Path = None):
        self.db_path = db_path or DB_PATH
        self._ensure_table()

    # ── 数据库连接 ──

    def _connect(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_table(self):
        """自动创建 site_configs 表（如果不存在）"""
        conn = self._connect()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS site_configs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                site_name  TEXT UNIQUE NOT NULL,
                site_url   TEXT NOT NULL,
                search_type TEXT DEFAULT 'both',
                keywords   TEXT DEFAULT '',
                days_back  INTEGER DEFAULT 7,
                search_url TEXT DEFAULT '',
                cron_expr  TEXT DEFAULT '0 9 * * *',
                enabled    INTEGER DEFAULT 1,
                proxy      TEXT,
                notes      TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
        conn.close()

    # ── 查询 ──

    def get_all(self, enabled_only: bool = True) -> List[SiteConfig]:
        """
        获取所有站点配置。

        Args:
            enabled_only: 仅返回已启用的站点
        """
        conn = self._connect()
        try:
            if enabled_only:
                rows = conn.execute(
                    "SELECT * FROM site_configs WHERE enabled=1 ORDER BY site_name"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM site_configs ORDER BY site_name"
                ).fetchall()
            return [self._row_to_config(r) for r in rows]
        finally:
            conn.close()

    def get_by_name(self, site_name: str) -> Optional[SiteConfig]:
        """按站点名称查询单个配置"""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM site_configs WHERE site_name=?", (site_name,)
            ).fetchone()
            return self._row_to_config(row) if row else None
        finally:
            conn.close()

    def exists(self, site_name: str) -> bool:
        """检查站点是否存在"""
        return self.get_by_name(site_name) is not None

    # ── 增删改 ──

    def save(self, site_name: str, site_url: str, search_type: str = "both",
             keywords: str = "", days_back: int = 7, search_url: str = "",
             cron_expr: str = "0 9 * * *", enabled: bool = True,
             proxy: str = "", notes: str = "") -> bool:
        """
        新增或更新站点配置。按 site_name 判断是否存在。

        Returns:
            是否操作成功
        """
        conn = self._connect()
        try:
            existing = conn.execute(
                "SELECT id FROM site_configs WHERE site_name=?", (site_name,)
            ).fetchone()

            if existing:
                conn.execute("""
                    UPDATE site_configs SET
                        site_url=?, search_type=?, keywords=?, days_back=?,
                        search_url=?, cron_expr=?, enabled=?, proxy=?, notes=?,
                        updated_at=datetime('now')
                    WHERE site_name=?
                """, (
                    site_url, search_type, keywords, days_back,
                    search_url, cron_expr, int(enabled), proxy or "", notes,
                    site_name,
                ))
                logger.info(f"已更新站点: {site_name}")
            else:
                conn.execute("""
                    INSERT INTO site_configs
                        (site_name, site_url, search_type, keywords, days_back,
                         search_url, cron_expr, enabled, proxy, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    site_name, site_url, search_type, keywords, days_back,
                    search_url, cron_expr, int(enabled), proxy or "", notes,
                ))
                logger.info(f"已新增站点: {site_name}")

            conn.commit()
            return True
        except Exception as e:
            logger.error(f"保存站点配置失败: {e}")
            return False
        finally:
            conn.close()

    def delete(self, site_name: str) -> bool:
        """删除指定站点配置"""
        conn = self._connect()
        try:
            conn.execute("DELETE FROM site_configs WHERE site_name=?", (site_name,))
            conn.commit()
            logger.info(f"已删除站点: {site_name}")
            return True
        except Exception as e:
            logger.error(f"删除站点失败: {e}")
            return False
        finally:
            conn.close()

    def delete_all(self) -> int:
        """清空所有站点配置，返回删除行数"""
        conn = self._connect()
        try:
            cur = conn.execute("DELETE FROM site_configs")
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    # ── Excel 导入 ──

    def import_from_excel(self, file_path: str, replace_all: bool = False) -> dict:
        """
        从 Excel 文件导入站点配置。

        Args:
            file_path: Excel 文件路径
            replace_all: 是否先清空所有现有配置再导入

        Returns:
            {"success": int, "skipped": int, "errors": List[str], "total": int}
        """
        import pandas as pd
        from utils.excel_reader import ExcelReader

        errors = []
        result = {"success": 0, "skipped": 0, "errors": errors, "total": 0}

        # 1. 读取 Excel
        try:
            reader = ExcelReader(Path(file_path))
            # 读取时不过滤 enabled，因为我们要让用户决定
            df = pd.read_excel(file_path)
            reader.COLUMN_ALIASES_INV = {v: k for k, v in reader.COLUMN_ALIASES.items()}
            df.rename(columns=reader.COLUMN_ALIASES, inplace=True)
        except Exception as e:
            errors.append(f"读取 Excel 失败: {e}")
            return result

        # 校验必填列
        missing = [c for c in ["site_name", "site_url"] if c not in df.columns]
        if missing:
            errors.append(f"Excel 缺少必填列: {missing}")
            return result

        # 2. 可选：清空现有配置
        if replace_all:
            self.delete_all()

        # 3. 逐行导入
        for idx, row in df.iterrows():
            site_name = str(row.get("site_name", "")).strip()
            if not site_name:
                errors.append(f"第 {idx+2} 行: site_name 为空")
                continue

            site_url = str(row.get("site_url", "")).strip()
            if not site_url:
                errors.append(f"第 {idx+2} 行 [{site_name}]: site_url 为空")
                continue

            # 解析关键词
            kw = str(row.get("keywords", "")).strip()
            keywords = kw if kw and kw.lower() != "nan" else ""

            # 解析 days_back
            days_back = 7
            if "days_back" in df.columns:
                dw = row.get("days_back", 7)
                try:
                    if str(dw).lower() != "nan":
                        days_back = max(1, int(float(str(dw))))
                except (ValueError, TypeError):
                    pass

            # 解析 enabled
            enabled = True
            if "enabled" in df.columns:
                ev = row.get("enabled", True)
                if isinstance(ev, str):
                    enabled = ev.strip().lower() in ("true", "1", "yes", "是")
                elif isinstance(ev, (int, float)):
                    enabled = bool(ev)

            # 解析 search_url (安全处理 NaN)
            search_url = ""
            if "search_url" in df.columns:
                su = row.get("search_url", "")
                try:
                    if pd.notna(su) and str(su).lower() != "nan":
                        search_url = str(su).strip()
                except Exception:
                    pass

            # 保存
            try:
                self.save(
                    site_name=site_name,
                    site_url=site_url,
                    search_type=str(row.get("search_type", "both")).strip(),
                    keywords=keywords,
                    days_back=days_back,
                    search_url=search_url,
                    cron_expr=str(row.get("cron_expr", "0 9 * * *")).strip(),
                    enabled=enabled,
                    proxy=str(row.get("proxy", "")).strip() if pd.notna(row.get("proxy", "")) else "",
                    notes=str(row.get("notes", "")).strip() if pd.notna(row.get("notes", "")) else "",
                )
                result["success"] += 1
            except Exception as e:
                errors.append(f"第 {idx+2} 行 [{site_name}]: 保存失败 - {e}")

        result["total"] = result["success"] + result["skipped"]
        logger.info(f"Excel 导入完成: {result['success']} 成功, {len(errors)} 错误")
        return result

    def export_to_excel(self, output_path: str) -> bool:
        """导出所有站点配置到 Excel 文件"""
        import pandas as pd

        configs = self.get_all(enabled_only=False)
        if not configs:
            logger.warning("没有站点配置可导出")
            return False

        rows = []
        for c in configs:
            rows.append({
                "site_name": c.site_name,
                "site_url": c.site_url,
                "search_type": c.search_type,
                "keywords": c.keywords_str,
                "days_back": c.days_back,
                "search_url": c.search_url,
                "cron_expr": c.cron_expr,
                "enabled": c.enabled,
                "proxy": c.proxy or "",
                "notes": c.notes,
            })

        df = pd.DataFrame(rows)
        df.to_excel(output_path, index=False)
        logger.info(f"已导出 {len(rows)} 个站点配置到: {output_path}")
        return True

    # ── 转换 ──

    @staticmethod
    def _row_to_config(row) -> SiteConfig:
        """将数据库行转换为 SiteConfig 数据类"""
        if row is None:
            return None

        # sqlite3.Row 不支持 .get()，统一用索引 + 默认值
        def _get(key, default=""):
            try:
                val = row[key]
                return val if val is not None else default
            except (IndexError, KeyError):
                return default

        kw = _get("keywords", "")
        keywords = [k.strip() for k in kw.split(",") if k.strip()] if kw else []
        return SiteConfig(
            site_name=_get("site_name", ""),
            site_url=_get("site_url", ""),
            search_type=_get("search_type", "both") or "both",
            keywords=keywords,
            days_back=int(_get("days_back", 7) or 7),
            search_url=_get("search_url", "") or "",
            cron_expr=_get("cron_expr", "0 9 * * *") or "0 9 * * *",
            enabled=bool(int(_get("enabled", 1) or 1)),
            proxy=_get("proxy") or None,
            notes=_get("notes", "") or "",
        )

    @staticmethod
    def config_to_dict(config: SiteConfig) -> dict:
        """将 SiteConfig 转为字典（用于 API 响应）"""
        return {
            "site_name": config.site_name,
            "site_url": config.site_url,
            "search_type": config.search_type,
            "keywords": config.keywords_str,
            "days_back": config.days_back,
            "search_url": config.search_url,
            "cron_expr": config.cron_expr,
            "enabled": config.enabled,
            "proxy": config.proxy or "",
            "notes": config.notes,
        }
