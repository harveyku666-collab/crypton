"""Address intelligence scheduled jobs."""

from __future__ import annotations

import logging

from app.common.database import db_available
from app.config import settings

logger = logging.getLogger("bitinfo.address_intel.jobs")


async def sync_address_intel_sources_job() -> None:
    if not db_available():
        return

    from app.address_intel.service import sync_monitored_address_sources

    try:
        result = await sync_monitored_address_sources(
            include_legacy=True,
            include_default_seeds=True,
            legacy_limit=settings.address_intel_legacy_sync_limit,
        )
        logger.info(
            "Address intel sync completed: count=%d created=%d updated=%d legacy=%d seeds=%d",
            result.get("count", 0),
            result.get("created", 0),
            result.get("updated", 0),
            result.get("source_counts", {}).get("legacy", 0),
            result.get("source_counts", {}).get("default_seeds", 0),
        )
    except Exception:
        logger.exception("Failed to sync address intelligence sources")


def register_address_intel_jobs() -> None:
    from app.common.scheduler import add_cron_job

    add_cron_job(
        sync_address_intel_sources_job,
        hour=settings.address_intel_sync_hour,
        minute=settings.address_intel_sync_minute,
        job_id="address_intel.sync.sources",
    )
    logger.info(
        "Address intel jobs registered (sync daily @ %02d:%02d)",
        settings.address_intel_sync_hour,
        settings.address_intel_sync_minute,
    )
