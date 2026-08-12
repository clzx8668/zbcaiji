"""
定时调度器
基于 APScheduler，支持 Cron 表达式、间隔触发、手动触发。
"""
from pathlib import Path
from typing import List, Optional, Callable
from loguru import logger
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.executors.pool import ThreadPoolExecutor
from utils.excel_reader import SiteConfig


class Scheduler:
    """定时任务调度管理器"""

    def __init__(self, db_path: Optional[Path] = None):
        """
        Args:
            db_path: 保留参数（兼容性），当前使用内存存储
        """
        executors = {
            # 串行执行：避免多个 Playwright 实例并发导致冲突与频控
            "default": ThreadPoolExecutor(max_workers=1),
        }

        job_defaults = {
            "coalesce": True,          # 合并错过的任务
            "max_instances": 1,        # 同一任务最多一个实例
            "misfire_grace_time": 300, # 错过5分钟内仍执行
        }

        self._scheduler = BackgroundScheduler(
            executors=executors,
            job_defaults=job_defaults,
        )
        self._crawl_func: Optional[Callable] = None

    def set_crawl_function(self, func: Callable):
        """设置爬取执行函数"""
        self._crawl_func = func

    def add_site_jobs(self, configs: List[SiteConfig]):
        """
        从站点配置列表注册定时任务

        Args:
            configs: 站点配置列表
        """
        if not self._crawl_func:
            raise RuntimeError("请先调用 set_crawl_function 设置爬取函数")

        for config in configs:
            if not config.enabled:
                continue

            job_id = f"crawl_{config.site_name}"

            # 移除已有同名任务
            if self._scheduler.get_job(job_id):
                self._scheduler.remove_job(job_id)

            # 解析 cron 表达式
            try:
                parts = config.cron_expr.strip().split()
                if len(parts) == 5:
                    minute, hour, day, month, day_of_week = parts
                    trigger = CronTrigger(
                        minute=minute,
                        hour=hour,
                        day=day,
                        month=month,
                        day_of_week=day_of_week,
                    )
                else:
                    logger.warning(f"无效的 Cron 表达式 '{config.cron_expr}'，使用默认: 每天 9:00")
                    trigger = CronTrigger(hour=9, minute=0)

                self._scheduler.add_job(
                    self._crawl_func,
                    trigger=trigger,
                    args=[config],
                    id=job_id,
                    name=f"爬取: {config.site_name}",
                    replace_existing=True,
                )
                logger.info(
                    f"已注册定时任务: [{config.site_name}] "
                    f"Cron='{config.cron_expr}' 关键词={config.keywords_str}"
                )
            except Exception as e:
                logger.error(f"注册任务失败 [{config.site_name}]: {e}")

    def add_interval_job(self, func: Callable, hours: int = 12, job_id: str = "default_interval"):
        """添加间隔执行的通用任务"""
        from apscheduler.triggers.interval import IntervalTrigger
        self._scheduler.add_job(
            func,
            trigger=IntervalTrigger(hours=hours),
            id=job_id,
            replace_existing=True,
        )

    def run_now(self, config: SiteConfig):
        """立即手动执行一次爬取"""
        if not self._crawl_func:
            raise RuntimeError("请先调用 set_crawl_function 设置爬取函数")
        logger.info(f"手动触发爬取: {config.site_name}")
        return self._crawl_func(config)

    def start(self):
        """启动调度器"""
        self._scheduler.start()
        logger.info("调度器已启动")
        self._print_jobs()

    def shutdown(self, wait: bool = True):
        """关闭调度器"""
        self._scheduler.shutdown(wait=wait)
        logger.info("调度器已关闭")

    def _print_jobs(self):
        jobs = self._scheduler.get_jobs()
        if jobs:
            logger.info(f"当前已注册 {len(jobs)} 个定时任务:")
            for job in jobs:
                logger.info(f"  [{job.id}] {job.name} -> next: {job.next_run_time}")
        else:
            logger.info("当前无已注册的定时任务")

    def is_running(self) -> bool:
        """检查调度器是否在运行"""
        return self._scheduler.running
