"""APScheduler wrapper — start/stop via FastAPI lifespan."""

from __future__ import annotations

import logging
from typing import Callable, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("bitinfo.scheduler")

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


def add_interval_job(
    func: Callable,
    *,
    seconds: int = 0,
    minutes: int = 0,
    hours: int = 0,
    job_id: str | None = None,
    **kwargs: Any,
) -> None:
    sched = get_scheduler()
    sched.add_job(
        func,
        IntervalTrigger(seconds=seconds, minutes=minutes, hours=hours),
        id=job_id or func.__qualname__,
        replace_existing=True,
        **kwargs,
    )


def add_cron_job(
    func: Callable,
    *,
    hour: int | str = "*",
    minute: int | str = "0",
    day: int | str | None = None,
    day_of_week: str | None = None,
    job_id: str | None = None,
    **kwargs: Any,
) -> None:
    sched = get_scheduler()
    trigger_kwargs: dict[str, Any] = {"hour": hour, "minute": minute}
    if day is not None:
        trigger_kwargs["day"] = day
    if day_of_week is not None:
        trigger_kwargs["day_of_week"] = day_of_week
    sched.add_job(
        func,
        CronTrigger(**trigger_kwargs),
        id=job_id or func.__qualname__,
        replace_existing=True,
        **kwargs,
    )


def start_scheduler() -> None:
    sched = get_scheduler()
    if not sched.running:
        sched.start()
        logger.info("Scheduler started")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
    _scheduler = None
