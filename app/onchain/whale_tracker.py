"""Whale address monitoring compatibility wrapper."""

from __future__ import annotations

from typing import Any

from app.common.cache import cached
from app.onchain.monitor_service import get_recent_transactions as get_recent_transactions_from_db


@cached(ttl=60, prefix="whale")
async def get_recent_transactions(min_value: int = 1_000_000, limit: int = 20) -> list[dict[str, Any]]:
    """Return recently stored whale transfer events."""
    return await get_recent_transactions_from_db(min_value=min_value, limit=limit)
