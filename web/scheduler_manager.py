"""
调度器管理器 — 在 Flask 进程内管理 APScheduler 的生命周期。
"""
import traceback
from datetime import datetime
from pathlib import Path
from loguru import logger
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
from config.settings import settings
from utils.site_config_manager import SiteConfigManager


class TaskManager:
    """
    封装 APScheduler + 爬取逻辑，提供 Web API 可调用的接口。
    """

    def __init__(self):
        self.scheduler: BackgroundScheduler = None
        self._crawl_func = None
        self._configs = []

    def set_crawl_function(self, func):
        """设置爬取执行函数（由 run.py 注入 _run_crawl）"""
        self._crawl_func = func

    def load_configs(self):
        """从数据库加载启用的站点配置"""
        try:
            mgr = SiteConfigManager()
            self._configs = mgr.get_all(enabled_only=True)
            logger.info(f"已加载 {len(self._configs)} 个站点配置")
        except Exception as e:
            logger.warning(f"加载配置失败: {e}")
            self._configs = []

        return self._configs

    def reload_configs(self) -> dict:
        """重新加载站点配置，并同步更新调度器中的任务"""
        old_count = len(self._configs)
        self.load_configs()
        new_count = len(self._configs)
        logger.info(f"配置重新加载: {old_count} → {new_count}")

        # 如果调度器正在运行，同步更新任务
        if self.scheduler and self.scheduler.running and self._crawl_func:
            current_job_ids = {f"crawl_{c.site_name}" for c in self._configs}
            existing_ids = {job.id for job in self.scheduler.get_jobs()}

            # 移除已不存在的任务
            for job_id in existing_ids - current_job_ids:
                try:
                    self.scheduler.remove_job(job_id)
                    logger.info(f"已移除调度任务: {job_id}")
                except Exception:
                    pass

            # 添加或更新任务
            for config in self._configs:
                job_id = f"crawl_{config.site_name}"
                try:
                    from apscheduler.triggers.cron import CronTrigger
                    trigger = CronTrigger.from_crontab(config.cron_expr, timezone="Asia/Shanghai")
                except Exception:
                    trigger = CronTrigger(hour=9, timezone="Asia/Shanghai")

                self.scheduler.add_job(
                    self._crawl_func,
                    trigger=trigger,
                    args=[config],
                    id=job_id,
                    replace_existing=True,
                    name=config.site_name,
                )

            logger.info(f"调度任务已同步: {len(self._configs)} 个活跃任务")

        return {"success": True, "config_count": new_count}

    def start(self) -> dict:
        """启动调度器"""
        if self.scheduler and self.scheduler.running:
            return {"success": False, "message": "调度器已在运行中"}

        if not self._crawl_func:
            return {"success": False, "message": "爬取函数未注入，无法启动"}

        self.load_configs()

        if not self._configs:
            return {"success": False, "message": "没有启用的站点配置"}

        self.scheduler = BackgroundScheduler(
            timezone="Asia/Shanghai",
            # 串行执行：避免多个 Playwright 实例并发导致冲突与频控
            executors={
                "default": ThreadPoolExecutor(max_workers=1),
            },
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 300,
            },
        )

        for config in self._configs:
            try:
                from apscheduler.triggers.cron import CronTrigger
                trigger = CronTrigger.from_crontab(config.cron_expr, timezone="Asia/Shanghai")
            except Exception:
                trigger = CronTrigger(hour=9, timezone="Asia/Shanghai")

            job_id = f"crawl_{config.site_name}"
            self.scheduler.add_job(
                self._crawl_func,
                trigger=trigger,
                args=[config],
                id=job_id,
                replace_existing=True,
                name=config.site_name,
            )
            logger.info(f"已注册定时任务: {config.site_name} ({config.cron_expr})")

        self.scheduler.start()
        logger.info("调度器已启动")
        return {"success": True, "message": f"调度器已启动，注册了 {len(self._configs)} 个任务"}

    def stop(self) -> dict:
        """停止调度器"""
        if not self.scheduler or not self.scheduler.running:
            return {"success": False, "message": "调度器未在运行"}

        self.scheduler.shutdown(wait=False)
        self.scheduler = None
        logger.info("调度器已停止")
        return {"success": True, "message": "调度器已停止"}

    def run_once(self, site_name: str) -> dict:
        """立即执行单个站点的爬取"""
        if not self._crawl_func:
            return {"success": False, "message": "爬取函数未注入"}

        if not self._configs:
            self.load_configs()

        config = next((c for c in self._configs if c.site_name == site_name), None)
        if not config:
            return {"success": False, "message": f"未找到站点配置: {site_name}"}

        try:
            logger.info(f"手动触发爬取: {site_name}")
            result = self._crawl_func(config)
            return {
                "success": True,
                "message": f"{site_name} 爬取完成",
                "data": result,
            }
        except Exception as e:
            logger.error(f"手动爬取 {site_name} 失败: {e}\n{traceback.format_exc()}")
            return {"success": False, "message": f"爬取失败: {str(e)}"}

    def get_status(self) -> dict:
        """获取调度器运行状态"""
        running = self.scheduler is not None and self.scheduler.running

        jobs = []
        if running:
            for job in self.scheduler.get_jobs():
                jobs.append({
                    "id": job.id,
                    "name": job.name,
                    "next_run": str(job.next_run_time) if job.next_run_time else None,
                    "trigger": str(job.trigger),
                })

        return {
            "running": running,
            "jobs": jobs,
            "job_count": len(jobs),
        }
