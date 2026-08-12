"""更新站点配置：URL 与备注（UTF-8 安全）。"""

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "bid_scraper.db"


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    updates = [
        (
            "https://bid.cnooc.com.cn/",
            "中海油官方采办平台已迁移至供应链数字化平台 bid.cnooc.com.cn（旧站 buy.cnooc.com.cn 302 故障）；适配器直连 API 采集",
            "中海油采办业务管理与交易系统",
        ),
        (
            "https://www.cnpcbidding.com/",
            "中石油官方招标平台；SPA+图形验证码，需交互模式首次人工验证，会话自动保存",
            "中国石油招标投标网",
        ),
        (
            "https://ec.chng.com.cn/",
            "华能官方电子商务平台；有 JS 反爬（412），适配器已处理并支持关键词搜索",
            "中国华能集团电子商务平台",
        ),
    ]
    for url, notes, name in updates:
        cur.execute(
            "UPDATE site_configs SET site_url=?, notes=? WHERE site_name=?",
            (url, notes, name),
        )
        print(f"{name}: updated {cur.rowcount}")
    con.commit()
    cur.execute(
        "SELECT id, site_name, site_url, notes FROM site_configs WHERE id IN (14,16,18)"
    )
    for r in cur.fetchall():
        print(r)
    con.close()


if __name__ == "__main__":
    main()
