"""探测页面弹窗/验证码 DOM 与 localStorage 状态。"""

import argparse
import sys
import time


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--wait-ms", type=int, default=9000)
    parser.add_argument("--no-headless", action="store_true")
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=not args.no_headless, args=["--no-proxy-server"]
        )
        page = browser.new_page(
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
        )
        try:
            page.goto(args.url, timeout=45000, wait_until="domcontentloaded")
        except Exception as e:
            print("[goto] 异常:", e)
        time.sleep(args.wait_ms / 1000)

        print("URL:", page.url)
        print("标题:", page.title())

        ls = page.evaluate("() => { const o = {}; for (let i=0;i<localStorage.length;i++){const k=localStorage.key(i); o[k]=String(localStorage.getItem(k)).slice(0,60);} return o; }")
        print("\nlocalStorage:", ls)

        dialogs = page.eval_on_selector_all(
            ".el-dialog, [class*='dialog'], [class*='modal'], [class*='mask'], [class*='Dialog']",
            """els => els.map(e => ({
                cls: (e.className || '').toString().slice(0, 80),
                display: getComputedStyle(e).display,
                visibility: getComputedStyle(e).visibility,
                text: (e.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 200)
            })).filter(x => x.display !== 'none' && x.visibility !== 'hidden')""",
        )
        print("\n弹窗:", dialogs[:8])

        # 查找验证码图片
        imgs = page.eval_on_selector_all(
            "img",
            """els => els.slice(0, 10).map(i => ({
                src: (i.src || '').slice(0, 80),
                w: i.width,
                h: i.height,
                cls: (i.className || '').toString().slice(0, 60)
            }))""",
        )
        print("\n页面图片:")
        for i in imgs:
            print("  ", i)

        # 验证码弹窗输入框
        inputs = page.eval_on_selector_all(
            ".el-dialog input, input",
            """els => els.slice(0, 12).map((e, i) => ({
                i: i,
                ph: (e.placeholder || '').slice(0, 40),
                id: e.id || '',
                cls: (e.className || '').toString().slice(0, 60),
                vis: getComputedStyle(e).display !== 'none'
            }))""",
        )
        print("\n输入框:")
        for x in inputs:
            print("  ", x)

        # 验证码图片 base64 抽取（如果有）
        cap = page.evaluate(
            """() => {
                const imgs = document.querySelectorAll('img');
                for (const i of imgs) {
                    if ((i.src || '').startsWith('data:image')) {
                        return {len: i.src.length, head: i.src.slice(0, 30)};
                    }
                }
                return null;
            }"""
        )
        print("\ndata:image 图片:", cap)
        browser.close()


if __name__ == "__main__":
    main()
