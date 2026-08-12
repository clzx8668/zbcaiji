"""抓取站点页面上所有 XHR/fetch 请求的请求体与响应体。

用法：
  python scripts/probe_api_capture.py --url "https://www.cnpcbidding.com/#/procurementNotice" --match "article" --wait-ms 8000
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--match", default="", help="只显示 URL 包含该串的请求")
    parser.add_argument("--wait-ms", type=int, default=8000)
    parser.add_argument("--no-headless", action="store_true")
    parser.add_argument("--save-json", default="")
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    captured = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=not args.no_headless,
            args=[
                "--no-proxy-server",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        def on_request(req):
            if req.resource_type not in ("xhr", "fetch"):
                return
            try:
                body = req.post_data or ""
            except Exception:
                body = ""
            captured.append(
                {
                    "kind": "req",
                    "method": req.method,
                    "url": req.url,
                    "body": body[:3000],
                }
            )

        def on_response(resp):
            if "xhr" not in str(resp.request.resource_type) and "fetch" not in str(
                resp.request.resource_type
            ):
                return
            try:
                body = resp.text()
            except Exception:
                body = ""
            captured.append(
                {
                    "kind": "resp",
                    "status": resp.status,
                    "url": resp.url,
                    "body": body[:6000],
                }
            )

        page.on("request", on_request)
        page.on("response", on_response)

        try:
            page.goto(args.url, timeout=45000, wait_until="domcontentloaded")
        except Exception as e:
            print(f"[goto] 异常: {e}")
        time.sleep(args.wait_ms / 1000)

        print("最终 URL:", page.url)
        print("标题:", page.title())
        print(f"捕获请求/响应: {len(captured)} 条")

        for c in captured:
            url = c["url"]
            if args.match and args.match not in url:
                continue
            if c["kind"] == "req":
                print(f"\n>>> REQ {c['method']} {url[:160]}")
                if c["body"]:
                    print(f"    body: {c['body'][:1200]}")
            else:
                print(f"\n<<< RESP [{c['status']}] {url[:160]}")
                b = c["body"]
                if b:
                    print(f"    body: {b[:1500]}")

        # 页面中的公告标题样例
        titles = page.eval_on_selector_all(
            "body",
            """els => {
                const t = [];
                const walker = document.createTreeWalker(els[0], NodeFilter.SHOW_TEXT);
                let n;
                const txt = {};
                while (n = walker.nextNode()) {
                    const v = n.nodeValue.trim();
                    if (v.length >= 12 && /公告|通知|采购|招标/.test(v)) {
                        txt[v] = (txt[v] || 0) + 1;
                    }
                }
                return Object.keys(txt).slice(0, 30);
            }""",
        )
        print("\n===== 正文长文本（疑似公告标题） =====")
        for t in titles or []:
            print("  -", t[:80])

        if args.save_json:
            out = ROOT / args.save_json
            out.write_text(
                json.dumps(captured, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            print(f"\n明细已保存: {out}")

        browser.close()


if __name__ == "__main__":
    main()
