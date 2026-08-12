"""中石油适配器自测：验证码检测 + 无头失败路径（UTF-8 安全）。"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from utils.excel_reader import SiteConfig  # noqa: E402
from sites import get_adapter  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg = SiteConfig(
        site_name="中国石油招标投标网",
        site_url="https://www.cnpcbidding.com/",
        keywords=["陶瓷膜", "水处理"],
        days_back=1,
    )
    adapter_cls = get_adapter(cfg.site_name)
    print("适配器:", adapter_cls)
    adapter = adapter_cls(cfg)
    print("MULTI_KEYWORD_SEARCH:", adapter.MULTI_KEYWORD_SEARCH)

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True, args=["--no-proxy-server"])
        ctx = b.new_context(
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
        )
        p = ctx.new_page()
        p.goto(adapter.get_search_url("陶瓷膜"), timeout=45000, wait_until="domcontentloaded")
        time.sleep(8)
        try:
            vis = p.locator(".el-dialog__wrapper").first.is_visible()
            txt = p.locator(".el-dialog__wrapper").first.inner_text()[:80]
            print("验证码弹窗可见:", vis, "| 文本:", txt.strip())
        except Exception as e:
            print("无弹窗或异常:", e)
        try:
            adapter.after_search(p, "陶瓷膜")
            print("after_search 未抛异常")
        except RuntimeError as e:
            print("按预期抛出 RuntimeError:", str(e)[:90])
        b.close()


if __name__ == "__main__":
    main()
