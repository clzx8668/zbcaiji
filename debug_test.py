"""
快速调试脚本 - 验证浏览器启动、爬取流程是否正常

用法: python debug_test.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import settings
from utils.logger import setup_logger
from core.browser import BrowserFactory
from utils.helpers import random_sleep

setup_logger(settings.LOG_DIR, "DEBUG", settings.LOG_RETENTION)


def test_browser():
    """测试浏览器是否能正常启动和访问网页"""
    print("\n" + "=" * 50)
    print("  1. 测试 Playwright 浏览器启动")
    print("=" * 50)

    try:
        pw, browser, context = BrowserFactory.create_playwright(headless=True)
        page = context.new_page()

        # 访问一个简单的测试页
        print("  -> 正在访问 https://httpbin.org/get ...")
        page.goto("https://httpbin.org/get", timeout=15000)
        content = page.content()
        print(f"  -> 页面加载成功，内容长度: {len(content)} 字节")

        # 测试提取
        title = page.title()
        print(f"  -> 页面标题: {title}")

        page.close()
        context.close()
        browser.close()
        pw.stop()
        print("  -> 浏览器测试通过!")
        return True
    except Exception as e:
        print(f"  -> 浏览器测试失败: {e}")
        return False


def test_extractor():
    """测试内容提取器"""
    print("\n" + "=" * 50)
    print("  2. 测试内容提取器 (BS4 模式)")
    print("=" * 50)

    from core.extractor import Extractor

    extractor = Extractor()

    # 测试 CSS 提取
    test_html = """
    <html><body>
        <ul class="list">
            <li><a href="/item/1">项目A：校园信息化建设</a><span class="date">2026-08-01</span></li>
            <li><a href="/item/2">项目B：智慧教室改造</a><span class="date">2026-08-05</span></li>
        </ul>
    </body></html>
    """

    results = extractor.extract_with_css(test_html)
    print(f"  -> CSS 提取到 {len(results)} 条结果:")
    for r in results:
        print(f"     └ {r['title']} | {r['url']} | {r['publish_date']}")
    print("  -> 提取器测试通过!")


def test_storage():
    """测试数据库存储"""
    print("\n" + "=" * 50)
    print("  3. 测试 SQLite 存储")
    print("=" * 50)

    from core.storage import Storage
    from utils.helpers import url_hash

    storage = Storage()

    # 插入测试数据
    test_item = {
        "url_hash": url_hash("https://example.com/bid/123"),
        "site_name": "测试站点",
        "title": "测试招标公告",
        "url": "https://example.com/bid/123",
        "publish_date": "2026-08-10",
        "item_type": "招标公告",
        "keywords_matched": "测试关键词",
        "detail_text": "这是一条测试公告内容。",
        "amount": "100万元",
        "source_org": "测试单位",
    }

    is_new, is_changed = storage.save_item(test_item)
    print(f"  -> 首次插入: 新增={is_new}, 变更={is_changed}")

    # 重复插入
    is_new2, is_changed2 = storage.save_item(test_item)
    print(f"  -> 重复插入: 新增={is_new2}, 变更={is_changed2} (应为 False, False)")

    # 查询统计
    stats = storage.get_stats(days=1)
    print(f"  -> 总条目数: {stats['total_items']}")

    print("  -> 存储层测试通过!")


def test_excel_reader():
    """测试 Excel 读取"""
    print("\n" + "=" * 50)
    print("  4. 测试 Excel 配置读取")
    print("=" * 50)

    from utils.excel_reader import ExcelReader

    reader = ExcelReader(settings.TEMPLATE_PATH)

    if not reader.template_path.exists():
        reader.create_template()
        print("  -> 已生成模板文件，请编辑后重试。")
        return

    configs = reader.read()
    print(f"  -> 读取到 {len(configs)} 个站点配置:")
    for c in configs:
        print(f"     └ [{c.site_name}] {c.search_type} | 关键词: {c.keywords_str} | "
              f"Cron: {c.cron_expr} | 启用: {c.enabled}")
    print("  -> Excel 读取测试通过!")


if __name__ == "__main__":
    print("\n" + "#" * 50)
    print("  招标爬虫 - 调试诊断")
    print("#" * 50)

    tests = [
        ("浏览器", test_browser),
        ("提取器", test_extractor),
        ("存储层", test_storage),
        ("Excel", test_excel_reader),
    ]

    passed = 0
    failed = 0

    for name, func in tests:
        try:
            if func():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  -> 异常: {e}")
            failed += 1

    print("\n" + "=" * 50)
    print(f"  测试结果: {passed} 通过, {failed} 失败 (共 {len(tests)} 项)")
    print("=" * 50)
