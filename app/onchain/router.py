"""On-chain monitoring API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.onchain.whale_tracker import get_recent_transactions
from app.onchain.exchange_flow import get_exchange_netflow, get_sopr

router = APIRouter(prefix="/onchain", tags=["onchain"])


@router.get("/whales")
async def whale_transactions(
    min_value: int = Query(1_000_000),
    limit: int = Query(20, le=100),
) -> list[dict[str, Any]]:
    return await get_recent_transactions(min_value, limit)


@router.get("/exchange-flow")
async def exchange_flow() -> dict[str, Any]:
    return await get_exchange_netflow()


@router.get("/sopr")
async def sopr() -> dict[str, Any]:
    return await get_sopr()
