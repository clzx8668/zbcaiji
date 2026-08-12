"""Web 记录页 UI 验证：筛选条件条/单独删除/固定列宽（UTF-8 安全）。"""

import sys
import base64
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

URL = "http://127.0.0.1:5010/admin/"
OUT = ROOT / "data" / "debug"
AUTH = "Basic " + base64.b64encode(b"admin:admin123").decode()


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True, args=["--no-proxy-server"])
        ctx = b.new_context(
            viewport={"width": 1440, "height": 900},
            extra_http_headers={"Authorization": AUTH},
        )
        p = ctx.new_page()
        p.goto(URL, timeout=30000, wait_until="domcontentloaded")
        p.wait_for_timeout(2500)

        # 概览页：筛选面板 + 条件条初始状态
        print("概览筛选面板:", p.locator("#tab-dashboard .filter-panel").count())
        print("概览条件条初始隐藏:", p.locator("#dashActiveFilters").is_hidden())

        # 选择类型=招标公告，应出现条件条
        p.select_option("#dashFilterType", "招标公告")
        p.wait_for_timeout(1800)
        print("选择类型后条件条显示:", p.locator("#dashActiveFilters").is_visible())
        chips = p.locator("#dashFilterChips .filter-chip")
        print("chips 数量:", chips.count(), "| 文本:", chips.first.inner_text() if chips.count() else "")

        # 再输入关键词
        p.fill("#dashFilterKeyword", "水处理")
        p.wait_for_timeout(1200)
        chips = p.locator("#dashFilterChips .filter-chip")
        print("增加关键词后 chips 数量:", chips.count())

        # 删除“类型”chip
        p.locator("#dashFilterChips .filter-chip").nth(0).locator(".chip-x").click()
        p.wait_for_timeout(1200)
        chips = p.locator("#dashFilterChips .filter-chip")
        print("删除类型 chip 后数量:", chips.count(), "| 剩余:", [c.inner_text().replace("\n"," ") for c in chips.all()])
        print("类型下拉已重置:", p.locator("#dashFilterType").input_value() == "")

        # 清空全部
        p.click("#dashActiveFilters .filter-clear")
        p.wait_for_timeout(1200)
        print("清空后条件条隐藏:", p.locator("#dashActiveFilters").is_hidden())

        p.screenshot(path=str(OUT / "spa_dash.png"))

        # 爬取资料页
        p.click('button[data-tab="items"]')
        p.wait_for_timeout(2200)
        print("\n爬取资料筛选面板:", p.locator("#tab-items .filter-panel").count())
        p.select_option("#filterType", "招标公告")
        p.wait_for_timeout(1800)
        chips = p.locator("#itemsFilterChips .filter-chip")
        print("items chips:", chips.count(), chips.first.inner_text().replace("\n"," ") if chips.count() else "")
        # 站点下拉选择
        sites = p.locator("#filterSite option")
        print("站点下拉选项数:", sites.count())
        if sites.count() > 1:
            val = sites.nth(1).get_attribute("value")
            p.select_option("#filterSite", val)
            p.wait_for_timeout(1800)
            chips = p.locator("#itemsFilterChips .filter-chip")
            print("加站点后 chips:", [c.inner_text().replace("\n"," ") for c in chips.all()])
        p.screenshot(path=str(OUT / "spa_items.png"))

        # 固定列宽检查
        layout = p.evaluate(
            """() => {
                const tbl = document.querySelector('#tab-items .table-custom');
                if (!tbl) return {err: 'no table'};
                const cs = getComputedStyle(tbl);
                const cols = tbl.querySelectorAll('colgroup col');
                return {
                    layout: cs.tableLayout,
                    width: tbl.offsetWidth,
                    colWidths: Array.from(cols).map(c => c.style.width)
                };
            }"""
        )
        print("\n表格布局:", layout)

        # 排序后列宽不变
        w1 = p.evaluate("() => document.querySelector('#tab-items .table-custom').offsetWidth")
        p.click("#tab-items th:nth-child(3)")
        p.wait_for_timeout(1600)
        w2 = p.evaluate("() => document.querySelector('#tab-items .table-custom').offsetWidth")
        print("排序前宽度:", w1, "排序后宽度:", w2, "| 稳定:", w1 == w2)
        # 站点列单元格宽度
        cw1 = p.evaluate("() => document.querySelector('#tab-items td:nth-child(3)').offsetWidth")
        p.click("#tab-items th:nth-child(4)")
        p.wait_for_timeout(1600)
        cw2 = p.evaluate("() => document.querySelector('#tab-items td:nth-child(3)').offsetWidth")
        print("站点列宽排序前后:", cw1, cw2, "| 稳定:", cw1 == cw2)
        p.screenshot(path=str(OUT / "spa_items_sorted.png"))

        # 归档页条件条
        p.click('button[data-tab="archive"]')
        p.wait_for_timeout(2200)
        p.select_option("#archFilterType", "招标公告")
        p.wait_for_timeout(1800)
        chips = p.locator("#archFilterChips .filter-chip")
        print("\n归档 chips:", chips.count(), chips.first.inner_text().replace("\n", " ") if chips.count() else "")
        p.screenshot(path=str(OUT / "spa_archive.png"))

        b.close()


if __name__ == "__main__":
    main()
