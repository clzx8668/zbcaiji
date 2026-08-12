"""带重试的浏览器探测：反复打开页面直到渲染成功，捕获 XHR 请求与响应。"""

import argparse
import json
import sys
import time
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
    parser.add_argument("--match", default="")
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--wait-ms", type=int, default=9000)
    parser.add_argument("--no-headless", action="store_true")
    parser.add_argument("--save-json", default="")
    parser.add_argument("--click", default="", help="等待后点击包含该文本的元素")
    parser.add_argument("--fill", default="", help="格式：选择器|关键词 输入后回车")
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    for attempt in range(1, args.retries + 1):
        print(f"\n===== 尝试 {attempt}/{args.retries} =====")
        captured = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=not args.no_headless, args=["--no-proxy-server"]
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
                    {"kind": "req", "method": req.method, "url": req.url, "body": body[:3000]}
                )

            def on_response(resp):
                rt = ""
                try:
                    rt = resp.request.resource_type
                except Exception:
                    pass
                if rt not in ("xhr", "fetch"):
                    return
                try:
                    body = resp.text()
                except Exception:
                    body = ""
                captured.append(
                    {"kind": "resp", "status": resp.status, "url": resp.url, "body": body[:8000]}
                )

            page.on("request", on_request)
            page.on("response", on_response)

            try:
                page.goto(args.url, timeout=60000, wait_until="domcontentloaded")
            except Exception as e:
                print("[goto] 异常:", e)
            time.sleep(args.wait_ms / 1000)

            body_text = page.evaluate("() => document.body.innerText.slice(0, 200)")
            print("页面文本头:", body_text[:200].replace("\n", " "))
            print("最终 URL:", page.url)

            if "502" in body_text or "Bad Gateway" in body_text or "504" in body_text:
                browser.close()
                time.sleep(3)
                continue

            # 点击目标元素
            if args.click:
                try:
                    page.get_by_text(args.click, exact=True).first.click(timeout=8000)
                    print(f"[+] 已点击: {args.click}")
                    time.sleep(5000 / 1000)
                except Exception as e:
                    print(f"[!] 点击失败: {e}")

            # 输入关键词
            if args.fill:
                sel, kw = args.fill.split("|", 1)
                try:
                    box = page.locator(sel).first
                    box.click(timeout=8000)
                    box.fill(kw)
                    box.press("Enter")
                    print(f"[+] 已输入: {kw}")
                    time.sleep(6000 / 1000)
                except Exception as e:
                    print(f"[!] 输入失败: {e}")

            print(f"捕获 {len(captured)} 条 XHR")
            for c in captured:
                url = c["url"]
                if args.match and args.match not in url:
                    continue
                if c["kind"] == "req":
                    print(f"\n>>> REQ {c['method']} {url[:170]}")
                    if c["body"]:
                        print(f"    body: {c['body'][:1000]}")
                else:
                    print(f"\n<<< RESP [{c['status']}] {url[:170]}")
                    print(f"    body: {c['body'][:1200]}")

            if args.save_json:
                out = ROOT / args.save_json
                out.write_text(json.dumps(captured, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"\n明细已保存: {out}")

            browser.close()
            if "502" not in body_text:
                break


if __name__ == "__main__":
    main()
