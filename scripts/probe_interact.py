"""交互探测：打开页面 → 在搜索框输入关键词回车 → 观察 URL/接口/结果变化。

用途：摸清 SPA 站点真实搜索行为（例如政采云系站点 /site/search?keyword= 不生效时）。

用法：
  python scripts/probe_interact.py --url "http://www.ccgp-shanghai.gov.cn/site/search?keyword=陶瓷膜" --keyword "陶瓷膜"
"""

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
    parser.add_argument("--keyword", required=True)
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    requests_before = set()
    requests_after = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-proxy-server"])
        page = browser.new_page(
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
        )

        def on_req(req):
            url = req.url
            if any(k in url.lower() for k in ["/api/", "search", "announce", "notice", "list", "query", "magic"]):
                requests_after.append(f"{req.method} {url}")

        page.on("request", on_req)

        print("[1] 打开:", args.url)
        try:
            page.goto(args.url, timeout=40000, wait_until="domcontentloaded")
        except Exception as e:
            print("    goto 异常:", e)
        time.sleep(6)
        print("    URL:", page.url)
        requests_before = set(requests_after)
        print("    加载期请求数:", len(requests_before))

        print("[2] 定位搜索框...")
        candidates = page.eval_on_selector_all(
            "input",
            """els => els.map((e, i) => ({
                i: i,
                ph: (e.placeholder || '').slice(0, 30),
                id: e.id || '',
                cls: (e.className || '').toString().slice(0, 50),
                type: e.type || ''
            })).filter(x => /搜索|检索|关键字|keyword|search/i.test(x.ph + x.id + x.cls) || x.type === 'search')""",
        )
        print("    候选:", candidates)

        picked = None
        for c in candidates:
            try:
                loc = page.locator(f"input").nth(c["i"])
                if loc.is_visible():
                    picked = loc
                    print("    选用 index", c["i"], c["ph"])
                    break
            except Exception:
                continue

        if picked is None:
            try:
                picked = page.locator("input[type='search'], input[placeholder*='搜索'], input[placeholder*='关键字']").first
                if picked.count():
                    print("    选用兜底输入框")
                else:
                    picked = None
            except Exception:
                picked = None

        if picked is None:
            print("[-] 未找到搜索框，退出")
            browser.close()
            return

        print("[3] 输入关键词并回车...")
        try:
            picked.click(timeout=8000)
            picked.fill(args.keyword)
            try:
                btn = page.locator("button.title-search").first
                if btn.count() and btn.is_visible():
                    btn.click(timeout=8000)
                    print("    已点击[搜标题]按钮")
                else:
                    picked.press("Enter")
                    print("    未找到[搜标题]按钮，按回车")
            except Exception:
                picked.press("Enter")
                print("    按钮点击异常，按回车")
        except Exception as e:
            print("    输入异常:", e)

        # 打印搜索框周边结构（找搜索按钮）
        try:
            wrap = page.evaluate(
                """() => {
                    const inp = document.querySelector('input.po-input__inner');
                    if (!inp) return '';
                    let el = inp.parentElement;
                    let out = [];
                    for (let i = 0; i < 4 && el; i++) {
                        out.push('<lv' + i + '>' + el.outerHTML.slice(0, 1200));
                        el = el.parentElement;
                    }
                    return out.join('\\n\\n');
                }"""
            )
            print("[3.5] 搜索框周边 DOM:\n", wrap[:3000])
        except Exception as e:
            print("[3.5] DOM 转储失败:", e)

        time.sleep(8)
        print("[4] 交互后 URL:", page.url)
        new_reqs = [r for r in requests_after if r not in requests_before]
        print("    新增请求:")
        for r in new_reqs[:30]:
            print("     ", r[:150])

        print("[5] 结果标题（前 8 条）:")
        titles = page.eval_on_selector_all(
            "a[href*='/site/detail']",
            """els => els.slice(0, 12).map(a => ({
                t: (a.textContent || '').trim().slice(0, 60),
                href: a.getAttribute('href') || ''
            })).filter(x => x.t.length > 4)""",
        )
        for t in titles[:8]:
            print("    -", t["t"], "|", t["href"][:80])

        stat = page.eval_on_selector_all(
            "body",
            r"""els => {
                const m = (els[0].innerText || '').match(/共\s*\d+\s*条|\d+\s*条记录|找到\s*\d+|为您找到[^\n]{0,30}/);
                return m ? m[0] : '';
            }""",
        )
        print("[6] 统计:", stat)
        browser.close()


if __name__ == "__main__":
    main()
