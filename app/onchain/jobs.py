"""On-chain monitoring scheduled jobs."""

from __future__ import annotations

import logging

logger = logging.getLogger("bitinfo.onchain.jobs")


async def monitor_whale_activity() -> None:
    """Periodic whale activity check."""
    from app.onchain.monitor_service import collect_whale_transfer_events
    try:
        result = await collect_whale_transfer_events()
        logger.info(
            "Whale monitor run completed: watched=%d stored=%d errors=%d",
            result.get("watched_address_count", 0),
            result.get("stored_event_count", 0),
            result.get("error_count", 0),
        )
    except Exception:
        logger.debug("Whale monitoring skipped", exc_info=True)


def register_onchain_jobs() -> None:
    from app.common.scheduler import add_interval_job
    from app.config import settings

    add_interval_job(
        monitor_whale_activity,
        minutes=settings.onchain_whale_monitor_interval_minutes,
        job_id="onchain.whale",
    )
    logger.info(
        "On-chain jobs registered (whale monitor every %d minutes)",
        settings.onchain_whale_monitor_interval_minutes,
    )
