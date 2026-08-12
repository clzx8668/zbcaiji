"""通用站点探测脚本：打开指定 URL，观察页面结构、结果列表、分页与网络请求。

用于开发新站点适配器前的结构侦察，可复用。

用法：
  python scripts/probe_site.py --url "http://www.ccgp-shanghai.gov.cn/site/search?keyword=陶瓷膜"
  python scripts/probe_site.py --url "https://example.com/search?kw=xx" --wait-ms 12000 --selector "ul.list"
  python scripts/probe_site.py --url "..." --no-headless

输出：
  - 页面标题 / 最终 URL
  - 同源 API 请求列表（可用于发现接口）
  - 链接样例（href + 文本 + 父级标签结构）
  - 结果容器 / 分页 / 登录验证码提示
  - HTML 快照保存到 data/debug/probe_*.html
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
    # Windows 控制台默认 GBK，转成 UTF-8 避免中文/特殊字符打印报错
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="要打开的 URL")
    parser.add_argument("--wait-ms", type=int, default=8000, help="加载后等待毫秒数")
    parser.add_argument("--selector", default="", help="额外等待的 CSS 选择器")
    parser.add_argument("--no-headless", action="store_true", help="显示浏览器窗口")
    parser.add_argument("--max-links", type=int, default=25, help="打印链接数量上限")
    parser.add_argument("--type-keyword", default="", help="在页面搜索框输入该关键词并回车")
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    api_calls = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.no_headless, args=["--no-proxy-server"])
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
            url = req.url
            if any(k in url.lower() for k in ["/api/", "search", "announce", "notice", "list", "query"]):
                api_calls.append({"method": req.method, "url": url})

        page.on("request", on_request)

        try:
            page.goto(args.url, timeout=45000, wait_until="domcontentloaded")
        except Exception as e:
            print(f"[!] goto 异常: {e}")

        if args.selector:
            try:
                page.wait_for_selector(args.selector, timeout=15000)
                print(f"[+] 选择器已出现: {args.selector}")
            except Exception:
                print(f"[-] 等待选择器超时: {args.selector}")

        # 交互模式：在搜索框输入关键词并回车
        if args.type_keyword:
            typed = page.eval_on_selector_all(
                "input",
                """els => {
                    const picks = els.filter(e => {
                        const s = (e.placeholder || '') + (e.id || '') + (e.className || '');
                        return /搜索|检索|关键字|keyword|search/i.test(s);
                    });
                    return picks.length ? (picks[0].id || picks[0].className || 'input') : '';
                }""",
            )
            print(f"[i] 搜索框候选: {typed or '未找到'}")
            try:
                box = page.locator("input").first
                box.click()
                box.fill(args.type_keyword)
                box.press("Enter")
                print(f"[+] 已输入关键词并回车: {args.type_keyword}")
                page.wait_for_load_state("domcontentloaded", timeout=20000)
            except Exception as e:
                print(f"[!] 输入搜索失败: {e}")
            time.sleep(6000)

        time.sleep(args.wait_ms / 1000)

        print("\n===== 基本信息 =====")
        print("标题:", page.title())
        print("最终 URL:", page.url)

        # 登录/验证码提示
        html = page.content()
        for kw in ["验证码", "登录", "扫码", "captcha", "频繁访问", "访问过于频繁"]:
            if kw in html:
                print(f"[!] 页面包含提示词: {kw}")

        # 网络请求（同源 API）
        print("\n===== 网络请求（API/搜索相关，去重） =====")
        seen = set()
        for c in api_calls:
            key = c["method"] + " " + c["url"].split("?")[0]
            if key not in seen:
                seen.add(key)
                print(f"  {c['method']} {c['url'][:150]}")

        # 链接样例
        print(f"\n===== 链接样例（前 {args.max_links} 个） =====")
        links = page.eval_on_selector_all(
            "a[href]",
            """els => els.slice(0, 120).map(a => ({
                href: a.getAttribute('href'),
                text: (a.textContent || '').trim().slice(0, 80),
                cls: (a.className || '').toString().slice(0, 60),
                parent: a.parentElement ? a.parentElement.tagName + '.' + (a.parentElement.className || '').toString().slice(0, 40) : ''
            })).filter(x => x.text.length >= 4)""",
        )
        for l in links[: args.max_links]:
            print(f"  [{l['parent']}] {l['text'][:50]} -> {l['href'][:90]}")

        # 结果条目结构（第一条 outerHTML）
        print("\n===== 结果条目结构（第一条） =====")
        item_html = page.eval_on_selector_all(
            "[class*='searchResList-content-item'], [class*='result-item'], [class*='list-item']",
            "els => els.length ? els[0].outerHTML.slice(0, 2500) : ''",
        )
        if item_html:
            print(item_html)

        # 结果数量统计文本
        print("\n===== 数量/统计文本 =====")
        stat = page.eval_on_selector_all(
            "body",
            r"""els => {
                const body = els[0].innerText;
                const m = body.match(/共\s*\d+\s*条|\d+\s*条记录|找到\s*\d+|为您找到[^\n]{0,30}/);
                return m ? m[0] : '';
            }""",
        )
        print("  ", (stat or "")[:120])

        # 结果容器特征
        print("\n===== 容器特征 =====")
        containers = page.eval_on_selector_all(
            "ul, table, .list, .result, [class*='list'], [class*='result'], [class*='item']",
            """els => {
                const out = [];
                for (const el of els) {
                    const links = el.querySelectorAll('a[href]').length;
                    if (links >= 3 && links <= 60 && el.textContent.length > 30) {
                        out.push({
                            tag: el.tagName,
                            cls: (el.className || '').toString().slice(0, 70),
                            links: links,
                            text: el.textContent.trim().slice(0, 60)
                        });
                    }
                }
                return out.slice(0, 12);
            }""",
        )
        for c in containers:
            print(f"  <{c['tag']} class='{c['cls']}'> links={c['links']} text={c['text'][:50]}")

        # 分页
        print("\n===== 分页 =====")
        pag2 = page.eval_on_selector_all(
            "[class*='page'], [class*='pager'], [class*='Pagination'], [class*='pagination']",
            """els => els.slice(0, 15).map(e => ({
                tag: e.tagName,
                cls: (e.className || '').toString().slice(0, 60),
                text: (e.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 80)
            }))""",
        )
        for p in pag2:
            if p["text"]:
                print(f"  <{p['tag']} class='{p['cls']}'> {p['text'][:60]}")
        pag = page.eval_on_selector_all(
            "a[href], [class*='page'] a, [class*='pagination'] a, [class*='pager'] a",
            """els => [...new Set(els.map(a => ({
                text: (a.textContent || '').trim().slice(0, 12),
                href: a.getAttribute('href') || ''
            })).filter(x => /页|>|\\d{1,2}/.test(x.text)).map(x => x.text + ' -> ' + x.href.slice(0, 80)))]""",
        )
        for p in pag[:12]:
            print("  ", p)

        # 保存快照
        debug_dir = ROOT / "data" / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = debug_dir / f"probe_{ts}.html"
        out.write_text(html, encoding="utf-8", errors="replace")
        print(f"\nHTML 快照已保存: {out}")

        browser.close()


if __name__ == "__main__":
    main()
