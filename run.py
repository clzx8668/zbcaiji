"""
招标/中标公告聚合爬虫工具 - 主入口 CLI

用法:
    # 生成模板 Excel
    python run.py init

    # 手动执行全部站点
    python run.py crawl --all

    # 手动执行指定站点
    python run.py crawl --site "中国政府采购网"

    # 启动定时调度
    python run.py schedule

    # 查看统计概览
    python run.py report

    # 导出报告
    python run.py export --format excel
    python run.py export --format json --site "中国政府采购网" --new

    # 启动 Web 管理后台
    python run.py web
    python run.py web --port 8080 --debug
"""
import sys
import threading
import traceback
from pathlib import Path
import click
from loguru import logger

# 确保项目根目录在 sys.path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config.settings import settings
from utils.logger import setup_logger
from utils.excel_reader import ExcelReader, SiteConfig
from utils.site_config_manager import SiteConfigManager
from core.crawler import Crawler
from core.storage import Storage
from core.scheduler import Scheduler
from export.reporter import Reporter

# 初始化日志
setup_logger(settings.LOG_DIR, settings.LOG_LEVEL, settings.LOG_RETENTION)

# 全局爬取互斥锁：保证任意时刻只有一个爬虫在跑，
# 避免多个 Playwright 实例并发导致 "Sync API inside asyncio loop" 及站点频控
_crawl_lock = threading.Lock()


def _run_crawl(config: SiteConfig, force_reanalyze: bool = False, 
               no_interact: bool = False, timeout_seconds: int = None) -> dict:
    """执行单个站点的爬取，返回统计（全局串行执行）"""
    storage = Storage()
    task_id = storage.create_task(config.site_name)

    try:
        with _crawl_lock:
            crawler = Crawler(
                config,
                force_reanalyze=force_reanalyze,
                no_interact=no_interact,
                timeout_seconds=timeout_seconds,
            )
            results = crawler.crawl()

        new_count = 0
        changed_count = 0

        for r in results:
            item_data = {
                "url_hash": r.url_hash,
                "site_name": config.site_name,
                "title": r.title,
                "url": r.url,
                "publish_date": r.publish_date,
                "item_type": r.item_type,
                "keywords_matched": r.keywords_matched,
                "detail_text": r.detail_text,
                "amount": r.amount,
                "source_org": r.source_org,
            }
            is_new, is_changed = storage.save_item(item_data)
            if is_new:
                new_count += 1
            elif is_changed:
                changed_count += 1

        storage.finish_task(task_id, "success", len(results), new_count)
        logger.info(
            f"[{config.site_name}] 完成: {len(results)} 条结果, "
            f"{new_count} 条新增, {changed_count} 条变更"
        )
        return {
            "site": config.site_name,
            "total": len(results),
            "new": new_count,
            "changed": changed_count,
        }
    except Exception as e:
        error_detail = traceback.format_exc()
        logger.error(f"[{config.site_name}] 爬取失败: {e}\n{error_detail}")
        storage.finish_task(task_id, "failed", 0, 0, str(e))
        return {"site": config.site_name, "total": 0, "new": 0, "changed": 0, "error": str(e)}


@click.group()
@click.version_option(version="1.0.0")
def cli():
    """招标/中标公告聚合爬虫工具"""


@cli.command("init")
def init_template():
    """生成 Excel 配置模板"""
    reader = ExcelReader(settings.TEMPLATE_PATH)
    path = reader.create_template()
    click.echo(f"模板已创建: {path}")
    click.echo("请在 Excel 中填写站点配置后，通过以下方式导入数据库：")
    click.echo("  方式1: Web 后台 → 系统工具 → Excel导入")
    click.echo("  方式2: python run.py seed")


@cli.command("seed")
@click.option("--file", "excel_file", default=None, help="Excel 文件路径（默认读取 config/template.xlsx）")
@click.option("--replace", is_flag=True, help="导入前清空数据库中的所有站点配置")
def seed_db(excel_file: str, replace: bool):
    """将 Excel 站点配置导入数据库"""
    path = Path(excel_file) if excel_file else settings.TEMPLATE_PATH
    if not path.exists():
        click.echo(f"文件不存在: {path}", err=True)
        click.echo("请先运行: python run.py init 生成模板", err=True)
        sys.exit(1)

    mgr = SiteConfigManager()
    result = mgr.import_from_excel(str(path), replace_all=replace)

    click.echo(f"导入完成: {result['success']} 成功, {len(result['errors'])} 错误")
    for err in result["errors"]:
        click.echo(f"  - {err}", err=True)

    if result["success"] > 0:
        configs = mgr.get_all(enabled_only=False)
        click.echo(f"数据库现有 {len(configs)} 个站点配置")


@cli.command("crawl")
@click.option("--all", "crawl_all", is_flag=True, help="爬取所有启用的站点")
@click.option("--site", default=None, help="指定站点名称（需与 Excel 中一致）")
@click.option("--engine", default=None,
              type=click.Choice(["playwright", "camoufox"]),
              help="浏览器引擎（默认从 .env 读取）")
@click.option("--reanalyze", is_flag=True, help="强制重新分析搜索入口（忽略缓存）")
@click.option("--no-interact", is_flag=True, help="禁用交互式提示（非 TTY 环境使用）")
def crawl_command(crawl_all: bool, site: str, engine: str, reanalyze: bool, no_interact: bool):
    """手动执行爬取任务"""
    if not crawl_all and not site:
        click.echo("请指定 --all（全部站点）或 --site（指定站点）", err=True)
        sys.exit(1)

    mgr = SiteConfigManager()
    configs = mgr.get_all(enabled_only=True)

    if not configs:
        click.echo("数据库中暂无启用的站点配置。")
        click.echo("请通过 Web 管理后台添加站点，或运行: python run.py seed 从 Excel 导入", err=True)
        sys.exit(0)

    if site:
        configs = [c for c in configs if c.site_name == site]
        if not configs:
            click.echo(f"未找到站点: {site}", err=True)
            all_sites = mgr.get_all(enabled_only=False)
            click.echo(f"可用站点: {[c.site_name for c in all_sites]}")
            sys.exit(1)

    # 设置引擎
    if engine:
        import os
        os.environ["BROWSER_ENGINE"] = engine

    click.echo(f"开始爬取 {len(configs)} 个站点...")
    stats = []
    for config in configs:
        stat = _run_crawl(config, force_reanalyze=reanalyze, no_interact=no_interact)
        stats.append(stat)

    # 汇总
    total_found = sum(s["total"] for s in stats)
    total_new = sum(s["new"] for s in stats)
    total_changed = sum(s["changed"] for s in stats)
    click.echo(f"\n{'='*50}")
    click.echo(f"爬取完成: {len(stats)} 个站点, {total_found} 条结果, "
               f"{total_new} 条新增, {total_changed} 条变更")
    click.echo(f"{'='*50}")


@cli.command("schedule")
def schedule_command():
    """启动定时调度器"""
    mgr = SiteConfigManager()
    configs = mgr.get_all(enabled_only=True)

    if not configs:
        click.echo("数据库中暂无启用的站点配置。请通过 Web 管理后台添加站点。")
        sys.exit(0)

    scheduler = Scheduler(db_path=settings.DATA_DIR / "scheduler_jobs.db")
    # 后台调度一律非交互，避免 input() 阻塞导致任务永久卡在 running
    scheduler.set_crawl_function(lambda c: _run_crawl(c, no_interact=True))
    scheduler.add_site_jobs(configs)
    scheduler.start()

    click.echo("调度器已启动，按 Ctrl+C 停止...")
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        click.echo("\n正在停止调度器...")
        scheduler.shutdown()
        click.echo("调度器已停止。")


@cli.command("report")
@click.option("--last", default="7d", help="统计最近多少天 (如 7d, 30d)")
@click.option("--site", default=None, help="按站点筛选")
@click.option("--type", "item_type", default=None,
              type=click.Choice(["招标公告", "中标公告"]),
              help="按公告类型筛选")
def report_command(last: str, site: str, item_type: str):
    """查看数据概览"""
    days = int(last.replace("d", "")) if "d" in last else 7

    storage = Storage()
    reporter = Reporter(storage)
    reporter.print_summary(days=days)

    if site or item_type:
        items = storage.query_items(
            site_name=site,
            item_type=item_type,
            limit=20,
        )
        if items:
            click.echo("\n最近 20 条记录:")
            for item in items:
                click.echo(f"  [{item['publish_date']}] {item['title'][:60]} "
                          f"({item['site_name']})")


@cli.command("web")
@click.option("--host", default="0.0.0.0", help="监听地址")
@click.option("--port", default=5000, type=int, help="监听端口")
@click.option("--debug", is_flag=True, help="调试模式")
def web_command(host: str, port: int, debug: bool):
    """启动 Web 管理后台"""
    from web.app import create_app
    from web.scheduler_manager import TaskManager

    # 初始化 TaskManager
    task_manager = TaskManager()
    # 后台调度一律非交互，避免 input() 阻塞导致任务永久卡在 running
    task_manager.set_crawl_function(lambda c: _run_crawl(c, no_interact=True))

    app = create_app(task_manager=task_manager)

    # 启动自动备份
    from web.backup import start_auto_backup
    start_auto_backup()

    click.echo(f"Web 管理后台启动: http://{host}:{port}/admin")
    click.echo(f"默认账户: admin / admin123")
    app.run(host=host, port=port, debug=debug, use_reloader=False)


@cli.command("export")
@click.option("--format", "fmt", default="excel",
              type=click.Choice(["excel", "json"]),
              help="导出格式")
@click.option("--site", default=None, help="按站点筛选")
@click.option("--from", "date_from", default=None, help="起始日期 (YYYY-MM-DD)")
@click.option("--to", "date_to", default=None, help="截止日期 (YYYY-MM-DD)")
@click.option("--type", "item_type", default=None,
              type=click.Choice(["招标公告", "中标公告"]),
              help="按公告类型筛选")
@click.option("--new", "new_only", is_flag=True, help="仅导出最近7天的新增")
@click.option("--output", default=None, help="输出目录")
def export_command(fmt: str, site: str, date_from: str, date_to: str,
                  item_type: str, new_only: bool, output: str):
    """导出爬取报告"""
    storage = Storage()
    output_dir = Path(output) if output else settings.OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    reporter = Reporter(storage, output_dir)

    if fmt == "excel":
        path = reporter.export_excel(
            site_name=site,
            date_from=date_from,
            date_to=date_to,
            item_type=item_type,
            new_only=new_only,
        )
    else:
        path = reporter.export_json(
            site_name=site,
            date_from=date_from,
            date_to=date_to,
            new_only=new_only,
        )

    click.echo(f"报告已导出: {path}")


@cli.command("login")
@click.option("--site", default=None, required=True, help="站点名称（需与数据库中的站点名一致）")
def login_command(site: str):
    """
    交互式登录：打开有头浏览器，手动完成微信/扫码登录后保存会话。
    登录后的会话会自动保存到 data/browser_sessions/，下次爬取该站点时自动加载。
    """
    from core.browser import BrowserFactory

    site_name = site.strip()
    click.echo(f"正在为站点 [{site_name}] 启动登录浏览器...")
    click.echo("请在浏览器窗口中完成登录操作。")
    click.echo("登录完成后，回到此处按 Enter 保存会话。")
    click.echo("按 Ctrl+C 或输入 'quit' 退出。")

    driver, browser, ctx = BrowserFactory.create_playwright(
        headless=False,
        session_name=site_name,
    )
    page = ctx.new_page()

    try:
        # 从数据库获取站点 URL
        from utils.site_config_manager import SiteConfigManager
        mgr = SiteConfigManager()
        config = mgr.get_by_name(site_name)
        if not config:
            click.echo(f"站点 [{site_name}] 不在数据库中。请先在 Web 管理后台添加该站点。")
            browser.close()
            driver.stop()
            return

        # 打开站点首页
        target_url = config.site_url
        click.echo(f"打开站点: {target_url}")
        page.goto(target_url, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=30000)

        # 等待用户手动登录
        click.echo(f"\n{'='*50}")
        click.echo("请在浏览器中完成登录，然后回到此处按 Enter 保存。")
        click.echo(f"{'='*50}")
        input("> ")

        # 保存会话
        success = BrowserFactory.save_session(ctx, site_name)
        if success:
            click.echo(f"会话已保存: data/browser_sessions/{site_name}.json")
            click.echo("下次爬取将自动加载此登录状态。")
        else:
            click.echo("会话保存失败！")

    except KeyboardInterrupt:
        click.echo("\n已取消。")
    except Exception as e:
        click.echo(f"错误: {e}")
    finally:
        page.close()
        browser.close()
        driver.stop()


if __name__ == "__main__":
    cli()
