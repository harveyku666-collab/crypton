"""Square collection scheduled jobs."""

from __future__ import annotations

import logging

from app.common.database import db_available
from app.config import settings
from app.square.service import collect_square_items, generate_hot_coin_snapshot

logger = logging.getLogger("bitinfo.square.jobs")


async def collect_square_content() -> None:
    try:
        result = await collect_square_items(
            page_size=settings.square_collect_page_size,
            backfill_pages=settings.square_collect_backfill_pages,
            language=settings.square_default_language,
        )
        logger.info(
            "Collected %d square items across %d pages (%d duplicates skipped)",
            result.get("created", 0),
            result.get("pages", 0),
            result.get("skipped", 0),
        )
    except Exception:
        logger.exception("Failed to collect square content")


async def generate_daily_hot_coin_snapshot() -> None:
    if not db_available():
        return
    try:
        result = await generate_hot_coin_snapshot(limit=20, hours=24, kol_only=False)
        logger.info(
            "Generated daily square hot-coin snapshot %s with %d rows",
            result.get("snapshot_key"),
            result.get("count", 0),
        )
    except Exception:
        logger.exception("Failed to generate daily square hot-coin snapshot")


async def generate_daily_kol_hot_coin_snapshot() -> None:
    if not db_available():
        return
    try:
        result = await generate_hot_coin_snapshot(limit=20, hours=24, kol_only=True)
        logger.info(
            "Generated daily square KOL hot-coin snapshot %s with %d rows",
            result.get("snapshot_key"),
            result.get("count", 0),
        )
    except Exception:
        logger.exception("Failed to generate daily square KOL hot-coin snapshot")


def register_square_jobs() -> None:
    from app.common.scheduler import add_cron_job, add_interval_job

    add_interval_job(
        collect_square_content,
        minutes=settings.square_collect_interval_minutes,
        job_id="square.collect",
    )
    add_cron_job(generate_daily_hot_coin_snapshot, hour=8, minute=5, job_id="square.hot.snapshot.daily")
    add_cron_job(generate_daily_kol_hot_coin_snapshot, hour=8, minute=10, job_id="square.hot.snapshot.daily.kol")
    logger.info("Square jobs registered")
