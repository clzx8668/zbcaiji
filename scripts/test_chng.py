"""华能适配器自测：用项目浏览器工厂启动，走反爬 + 关键词搜索 + 详情（UTF-8 安全）。"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from utils.excel_reader import SiteConfig  # noqa: E402
from sites import get_adapter  # noqa: E402
from core.browser import BrowserFactory  # noqa: E402


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    kw = sys.argv[1] if len(sys.argv) > 1 else "水处理"
    cfg = SiteConfig(
        site_name="中国华能集团电子商务平台",
        site_url="https://ec.chng.com.cn/",
        keywords=["陶瓷膜", "水处理", "盐湖提锂", "磷酸铁锂"],
        days_back=7,
    )
    adapter = get_adapter(cfg.site_name)(cfg)
    print("适配器:", type(adapter).__name__)

    driver, browser, ctx = BrowserFactory.create_playwright(headless=True)
    page = ctx.new_page()
    try:
        page.goto(adapter.get_search_url(kw), timeout=60000, wait_until="domcontentloaded")
        print("goto 后 URL:", page.url)
        adapter._wait_challenge_pass(page)
        print("反爬通过, URL:", page.url)
        t0 = time.time()
        items = adapter._search_keyword(page, kw)
        print(f"关键词 [{kw}] 命中 {len(items)} 条, 耗时 {time.time()-t0:.1f}s")
        for it in items[:10]:
            print("----")
            print("标题:", it["title"][:90])
            print("日期:", it["publish_date"], "| 类型:", it["item_type"])
            print("正文:", it["detail_text"][:160])
    finally:
        browser.close()
        driver.stop()


if __name__ == "__main__":
    main()
