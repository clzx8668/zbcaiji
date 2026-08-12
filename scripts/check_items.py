"""查看数据库入库记录（UTF-8 安全）。"""

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    con = sqlite3.connect(str(ROOT / "data" / "bid_scraper.db"))
    cur = con.cursor()
    cur.execute(
        """
        SELECT site_name, COUNT(*) c, MAX(publish_date) mx
        FROM items
        WHERE site_name IN ('中海油采办业务管理与交易系统', '中国华能集团电子商务平台')
        GROUP BY site_name
        """
    )
    for r in cur.fetchall():
        print("站点统计:", r)
    print("\n最新记录:")
    cur.execute(
        """
        SELECT site_name, publish_date, substr(title,1,45), keywords_matched, length(detail_text)
        FROM items
        WHERE site_name LIKE '%中海油%' OR site_name LIKE '%华能%'
        ORDER BY publish_date DESC LIMIT 12
        """
    )
    for r in cur.fetchall():
        print(r)
    con.close()


if __name__ == "__main__":
    main()
