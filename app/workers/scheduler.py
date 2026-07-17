"""APScheduler jobs for WebDAV and cleanup."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

if TYPE_CHECKING:
    from app.config import Settings
    from app.services.cleanup_service import CleanupService
    from app.services.webdav_service import WebDAVService

logger = logging.getLogger(__name__)


class AppScheduler:
    def __init__(
        self,
        settings: "Settings",
        webdav: "WebDAVService",
        cleanup: "CleanupService | None" = None,
    ):
        self.settings = settings
        self.webdav = webdav
        self.cleanup = cleanup
        self.scheduler = AsyncIOScheduler()

    def start(self) -> None:
        self.reload_webdav_job()
        self.reload_cleanup_job()
        self.scheduler.start()
        logger.info("scheduler started")

    def stop(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def reload_webdav_job(self) -> None:
        job_id = "webdav_sync"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
        w = self.settings.webdav
        if not w.enabled or not w.cron:
            return
        try:
            parts = w.cron.split()
            if len(parts) != 5:
                logger.error("invalid cron: %s", w.cron)
                return
            trigger = CronTrigger(
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
                month=parts[3],
                day_of_week=parts[4],
            )
            self.scheduler.add_job(
                self._webdav_job,
                trigger=trigger,
                id=job_id,
                replace_existing=True,
                max_instances=1,
            )
            logger.info("webdav cron scheduled: %s", w.cron)
        except Exception as e:
            logger.error("failed to schedule webdav: %s", e)

    def reload_cleanup_job(self) -> None:
        job_id = "disk_cleanup"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
        if not self.cleanup:
            return
        cfg = self.settings.cleanup
        if not cfg.enabled and not cfg.delete_after_sync:
            return
        interval = max(60, int(cfg.interval_sec or 300))
        self.scheduler.add_job(
            self._cleanup_job,
            trigger=IntervalTrigger(seconds=interval),
            id=job_id,
            replace_existing=True,
            max_instances=1,
        )
        logger.info("cleanup every %ss (max_gb=%s)", interval, cfg.max_gb)

    async def _webdav_job(self) -> None:
        logger.info("scheduled webdav sync starting")
        try:
            result = await self.webdav.sync_now()
            logger.info("scheduled webdav result: %s", result)
            if self.cleanup:
                await self.cleanup.run_all()
        except Exception:
            logger.exception("scheduled webdav failed")

    async def _cleanup_job(self) -> None:
        if not self.cleanup:
            return
        try:
            await self.cleanup.run_all()
        except Exception:
            logger.exception("scheduled cleanup failed")
