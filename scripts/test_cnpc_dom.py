"""中石油 /tenders 页面 DOM 状态检查（UTF-8 安全）。"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True, args=["--no-proxy-server"])
        p = b.new_page()
        p.goto("https://www.cnpcbidding.com/#/tenders", timeout=45000, wait_until="domcontentloaded")
        time.sleep(12)
        info = p.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll('.el-dialog__wrapper').forEach((w, i) => {
                    const cs = getComputedStyle(w);
                    const inner = w.querySelector('.el-dialog');
                    out.push({
                        i: i,
                        wrapperDisplay: cs.display,
                        innerDisplay: inner ? getComputedStyle(inner).display : '',
                        h: Math.round(w.getBoundingClientRect().height),
                        text: (w.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 50)
                    });
                });
                return out;
            }"""
        )
        for x in info:
            print(x)
        # 列表行数与搜索框
        rows = p.evaluate(
            """() => {
                const rows = document.querySelectorAll('.box_data.cursor_style');
                const out = [];
                rows.forEach(el => {
                    const t = (el.querySelector('.contant') || {}).textContent || '';
                    const ds = el.querySelectorAll('div');
                    const d = ds.length > 1 ? ds[1].textContent : '';
                    out.push((t + ' | ' + d).trim().replace(/\\s+/g, ' ').slice(0, 70));
                });
                return {count: rows.length, sample: out.slice(0, 8)};
            }"""
        )
        print("列表行数:", rows["count"])
        for r in rows["sample"]:
            print("  ", r)
        b.close()


if __name__ == "__main__":
    main()
