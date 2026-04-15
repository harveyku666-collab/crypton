"""Whale address monitoring — tracks large on-chain movements.

Data sources will be expanded; initial implementation uses public
blockchain explorers / aggregator APIs.
"""

from __future__ import annotations

import logging
from typing import Any

from app.common.http_client import fetch_json
from app.common.cache import cached
from app.common.database import async_session
from app.common.models import WhaleAlert

logger = logging.getLogger("bitinfo.onchain.whale")

WHALE_ALERT_API = "https://api.whale-alert.io/v1"


@cached(ttl=60, prefix="whale")
async def get_recent_transactions(min_value: int = 1_000_000, limit: int = 20) -> list[dict[str, Any]]:
    """Fetch recent large transactions.

    Note: whale-alert.io requires an API key for production use.
    This is a scaffold that returns empty results until configured.
    """
    # TODO: integrate with whale-alert.io or alternative (Arkham, Nansen)
    return []


async def store_whale_alert(alert: dict[str, Any]) -> None:
    try:
        async with async_session() as session:
            session.add(WhaleAlert(
                address=alert.get("address", "unknown"),
                action=alert.get("action", "transfer"),
                amount=float(alert.get("amount", 0)),
                token=alert.get("token", "BTC"),
                tx_hash=alert.get("tx_hash"),
            ))
            await session.commit()
    except Exception:
        logger.debug("DB store skipped for whale alert", exc_info=True)
