"""On-chain monitoring scheduled jobs."""

from __future__ import annotations

import logging

logger = logging.getLogger("bitinfo.onchain.jobs")


async def monitor_whale_activity() -> None:
    """Periodic whale activity check."""
    from app.onchain.whale_tracker import get_recent_transactions
    try:
        txns = await get_recent_transactions()
        if txns:
            logger.info("Detected %d whale transactions", len(txns))
    except Exception:
        logger.debug("Whale monitoring skipped", exc_info=True)


def register_onchain_jobs() -> None:
    from app.common.scheduler import add_interval_job

    add_interval_job(monitor_whale_activity, hours=1, job_id="onchain.whale")
    logger.info("On-chain jobs registered")
