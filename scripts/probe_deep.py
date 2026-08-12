"""深度探测脚本：打开 URL，记录所有请求/响应、跳转链、控制台消息与关键 JS 文件。

用于 SPA 壳/反爬站点的接口侦察（如中石油、中海油、华能）。

用法：
  python scripts/probe_deep.py --url "https://www.cnpcbidding.com/"
  python scripts/probe_deep.py --url "https://buy.cnooc.com.cn/" --wait-ms 15000
  python scripts/probe_deep.py --url "https://ec.chng.com.cn/" --no-headless
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
    parser.add_argument("--wait-ms", type=int, default=10000)
    parser.add_argument("--no-headless", action="store_true")
    parser.add_argument("--referer", default="", help="自定义 Referer 头")
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    requests_log = []
    responses_log = []
    console_log = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=not args.no_headless,
            args=[
                "--no-proxy-server",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        extra_headers = {}
        if args.referer:
            extra_headers["Referer"] = args.referer
        context = browser.new_context(
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
            extra_http_headers=extra_headers,
        )
        page = context.new_page()

        def on_request(req):
            if req.resource_type in ("document", "xhr", "fetch", "script", "stylesheet"):
                requests_log.append(
                    {"method": req.method, "url": req.url, "type": req.resource_type}
                )

        def on_response(resp):
            responses_log.append(
                {"status": resp.status, "url": resp.url}
            )

        def on_console(msg):
            if msg.type in ("error", "warning"):
                console_log.append(f"[{msg.type}] {msg.text[:300]}")

        def on_frame_navigated(frame):
            if frame == page.main_frame:
                print(f"[nav] {frame.url}")

        page.on("request", on_request)
        page.on("response", on_response)
        page.on("console", on_console)
        page.on("framenavigated", on_frame_navigated)

        try:
            resp = page.goto(args.url, timeout=45000, wait_until="domcontentloaded")
            if resp:
                print(f"[goto] status={resp.status} final={page.url}")
        except Exception as e:
            print(f"[goto] 异常: {e}")
            print(f"[goto] 当前 URL: {page.url}")

        time.sleep(args.wait_ms / 1000)

        print("\n===== 最终页面 =====")
        print("标题:", page.title())
        print("URL:", page.url)
        html = page.content()
        print("HTML 长度:", len(html))
        print("HTML 前 400 字符:", html[:400].replace("\n", " "))

        print("\n===== 导航链（document 请求） =====")
        for r in requests_log:
            if r["type"] == "document":
                print(f"  {r['method']} {r['url'][:180]}")

        print("\n===== API/JSON 请求 =====")
        for r in requests_log:
            if r["type"] in ("xhr", "fetch"):
                print(f"  {r['method']} {r['url'][:200]}")

        print("\n===== 响应状态（前 40，按 URL 去重） =====")
        seen = set()
        shown = 0
        for r in responses_log:
            key = r["url"].split("?")[0]
            if key in seen:
                continue
            seen.add(key)
            if r["status"] >= 400:
                print(f"  [{r['status']}] {r['url'][:180]}")
            shown += 1
        print(f"  (总响应 {len(responses_log)} 条，去重后 {shown} 条；上表仅列 4xx/5xx)")

        print("\n===== JS 脚本文件 =====")
        seen_js = set()
        for r in requests_log:
            if r["type"] == "script":
                u = r["url"]
                if u not in seen_js:
                    seen_js.add(u)
                    print(f"  {u[:180]}")

        print("\n===== 控制台错误/警告（前 15） =====")
        for c in console_log[:15]:
            print(" ", c)

        # 保存 HTML 快照
        debug_dir = ROOT / "data" / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = debug_dir / f"probe_deep_{ts}.html"
        out.write_text(html, encoding="utf-8", errors="replace")
        print(f"\nHTML 快照已保存: {out}")

        req_out = debug_dir / f"probe_deep_{ts}_requests.json"
        req_out.write_text(
            json.dumps(
                {"requests": requests_log, "responses": responses_log},
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        print(f"请求明细已保存: {req_out}")

        browser.close()


if __name__ == "__main__":
    main()
