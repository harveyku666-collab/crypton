"""On-chain monitoring API routes — Surf-powered wallet/whale/chain data."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Body
from pydantic import BaseModel, Field

from app.onchain.monitor_service import (
    collect_whale_transfer_events,
    get_whale_monitor_status,
    list_whale_alerts,
    list_whale_notification_channels,
    list_whale_notification_deliveries,
    list_whale_transfer_events,
    replay_whale_alert_notifications,
    upsert_whale_notification_channels,
)
from app.onchain.whale_tracker import get_recent_transactions
from app.onchain.exchange_flow import get_exchange_netflow, get_sopr
from app.market.sources import surf

router = APIRouter(prefix="/onchain", tags=["onchain"])


class WhaleNotificationChannelInput(BaseModel):
    name: str
    channel_type: str
    target: str
    min_severity: str = "medium"
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class WhaleAlertReplayInput(BaseModel):
    alert_ids: list[int] = Field(default_factory=list)
    severity: str | None = None
    limit: int = Field(20, ge=1, le=200)
    only_unsent: bool = True


@router.get("/whales")
async def whale_transactions(
    min_value: int = Query(1_000_000),
    limit: int = Query(20, le=100),
) -> list[dict[str, Any]]:
    return await get_recent_transactions(min_value, limit)


@router.get("/whale-monitor/events")
async def whale_monitor_events(
    chain: str | None = Query(None),
    address: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    items = await list_whale_transfer_events(chain=chain, address=address, limit=limit)
    return {
        "items": items,
        "count": len(items),
        "chain": chain,
        "address": address,
    }


@router.get("/whale-monitor/alerts")
async def whale_monitor_alerts(
    severity: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    items = await list_whale_alerts(severity=severity, limit=limit)
    return {
        "items": items,
        "count": len(items),
        "severity": severity,
    }


@router.post("/whale-monitor/alerts/replay")
async def whale_monitor_alert_replay(payload: WhaleAlertReplayInput) -> dict[str, Any]:
    return await replay_whale_alert_notifications(
        alert_ids=payload.alert_ids,
        severity=payload.severity,
        limit=payload.limit,
        only_unsent=payload.only_unsent,
    )


@router.get("/whale-monitor/channels")
async def whale_monitor_channels() -> dict[str, Any]:
    items = await list_whale_notification_channels()
    return {
        "items": items,
        "count": len(items),
    }


@router.post("/whale-monitor/channels/bulk-upsert")
async def whale_monitor_channel_bulk_upsert(items: list[WhaleNotificationChannelInput]) -> dict[str, Any]:
    return await upsert_whale_notification_channels([item.model_dump() for item in items])


@router.get("/whale-monitor/deliveries")
async def whale_monitor_deliveries(
    delivery_status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    items = await list_whale_notification_deliveries(delivery_status=delivery_status, limit=limit)
    return {
        "items": items,
        "count": len(items),
        "delivery_status": delivery_status,
    }


@router.get("/whale-monitor/status")
async def whale_monitor_status() -> dict[str, Any]:
    return await get_whale_monitor_status()


@router.post("/whale-monitor/run")
async def whale_monitor_run(
    force: bool = Body(False, embed=True),
) -> dict[str, Any]:
    return await collect_whale_transfer_events(force=force)


@router.get("/exchange-flow")
async def exchange_flow() -> dict[str, Any]:
    return await get_exchange_netflow()


@router.get("/sopr")
async def sopr() -> dict[str, Any]:
    return await get_sopr()


# ─── Wallet suite ────────────────────────────────────────────


@router.get("/wallet/{address}")
async def wallet_detail(address: str, chain: str = Query("ethereum")) -> dict[str, Any]:
    result = await surf.get_wallet_detail(address, chain)
    return result or {"error": f"No data for {address}"}


@router.get("/wallet/{address}/history")
async def wallet_history(address: str, chain: str = Query("ethereum"), limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.get_wallet_history(address, chain, limit)


@router.get("/wallet/{address}/protocols")
async def wallet_protocols(address: str, limit: int = Query(20, le=100)) -> list[dict]:
    from app.market.sources.surf import _run_surf, _extract_data
    result = await _run_surf("wallet-protocols", "--address", address, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@router.get("/wallet/{address}/transfers")
async def wallet_transfers(address: str, chain: str = Query("ethereum"), limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.get_wallet_transfers(address, chain, limit)


@router.get("/wallet/{address}/net-worth")
async def wallet_net_worth(address: str, time_range: str = Query("30d")) -> list[dict]:
    return await surf.get_wallet_net_worth(address, time_range)


@router.post("/wallet/labels-batch")
async def wallet_labels_batch(addresses: list[str] = Body(...)) -> list[dict]:
    return await surf.get_wallet_labels_batch(addresses)


# ─── Chain data ──────────────────────────────────────────────


@router.get("/gas-price")
async def gas_price(chain: str = Query("ethereum")) -> dict[str, Any]:
    result = await surf.get_gas_price(chain)
    return result or {"error": "No data"}


@router.get("/tx/{tx_hash}")
async def tx_detail(tx_hash: str, chain: str = Query("ethereum")) -> dict[str, Any]:
    result = await surf.get_tx_detail(tx_hash, chain)
    return result or {"error": f"No data for {tx_hash}"}


@router.get("/schema")
async def onchain_schema(chain: str = Query("ethereum")) -> Any:
    result = await surf.get_onchain_schema(chain)
    return result or {"error": "No schema"}


@router.post("/sql")
async def onchain_sql(query: str = Body(..., embed=True), chain: str = Body("ethereum", embed=True)) -> Any:
    result = await surf.get_onchain_sql(query, chain)
    return result or {"error": "Query failed"}


# ─── Rankings ────────────────────────────────────────────────


@router.get("/yield-ranking")
async def yield_ranking(limit: int = Query(20, le=100), sort_by: str = Query("apy")) -> list[dict]:
    from app.market.sources.defi_llama import get_yield_ranking
    return await get_yield_ranking(limit, sort_by)


@router.get("/bridge-ranking")
async def bridge_ranking(limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.get_bridge_ranking(limit)
