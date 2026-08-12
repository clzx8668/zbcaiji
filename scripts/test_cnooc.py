"""中海油适配器自测：近 N 天全量拉取 + 本地关键词过滤（UTF-8 安全）。"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from utils.excel_reader import SiteConfig  # noqa: E402
from sites.cnooc import CnoocSiteAdapter  # noqa: E402


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    cfg = SiteConfig(
        site_name="中海油采办业务管理与交易系统",
        site_url="https://bid.cnooc.com.cn/",
        keywords=["陶瓷膜", "水处理", "盐湖提锂", "磷酸铁锂"],
        days_back=days,
    )
    adapter = CnoocSiteAdapter(cfg)
    t0 = time.time()
    items = adapter.parse_result_list(None)
    print(f"耗时 {time.time()-t0:.1f}s, 命中 {len(items)} 条")
    for it in items:
        print("----")
        print("标题:", it["title"][:90])
        print("日期:", it["publish_date"], "| 类型:", it["item_type"], "| 词:", it["keywords_matched"])
        print("正文:", it["detail_text"][:200])


if __name__ == "__main__":
    main()
