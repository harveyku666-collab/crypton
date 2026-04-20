"""Whale transfer monitoring service."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from app.common.database import async_session, db_available
from app.common.models import MonitoredAddress, WhaleAlert, WhaleMonitorState, WhaleTransferEvent
from app.config import settings
from app.market.sources import surf

logger = logging.getLogger("bitinfo.onchain.monitor")

GLOBAL_SCOPE = "global"


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _safe_float(value: Any) -> float | None:
    try:
        if value in {None, ""}:
            return None
        return float(value)
    except Exception:
        return None


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _normalize_address(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("0x"):
        return text.lower()
    return text


def _normalize_direction(
    item: dict[str, Any],
    *,
    watched_address: str,
    from_address: str | None,
    to_address: str | None,
) -> str:
    action = str(item.get("direction") or item.get("action") or item.get("type") or "").strip().lower()
    if action in {"in", "incoming", "receive", "received"}:
        return "incoming"
    if action in {"out", "outgoing", "send", "sent"}:
        return "outgoing"
    if from_address and watched_address and from_address == watched_address:
        return "outgoing"
    if to_address and watched_address and to_address == watched_address:
        return "incoming"
    return "unknown"


def _normalize_transfer_item(item: dict[str, Any], watcher: MonitoredAddress) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None

    watched_address = str(watcher.address or "").strip().lower()
    from_address = _normalize_address(
        _first_non_empty(
            item.get("from_address"),
            item.get("from"),
            item.get("fromAddress"),
            item.get("sender"),
        )
    )
    to_address = _normalize_address(
        _first_non_empty(
            item.get("to_address"),
            item.get("to"),
            item.get("toAddress"),
            item.get("recipient"),
        )
    )
    direction = _normalize_direction(
        item,
        watched_address=watched_address,
        from_address=from_address,
        to_address=to_address,
    )
    counterparty = None
    if direction == "outgoing":
        counterparty = to_address
    elif direction == "incoming":
        counterparty = from_address
    else:
        counterparty = _normalize_address(item.get("counterparty") or item.get("counterparty_address"))

    token = _first_non_empty(
        item.get("token"),
        item.get("symbol"),
        item.get("token_symbol"),
        item.get("asset_symbol"),
        item.get("currency"),
    )
    tx_hash = _first_non_empty(
        item.get("tx_hash"),
        item.get("hash"),
        item.get("transaction_hash"),
        item.get("transactionHash"),
    )
    occurred_at = _first_non_empty(
        item.get("occurred_at"),
        item.get("timestamp"),
        item.get("time"),
        item.get("datetime"),
        item.get("date"),
        item.get("block_time"),
    )
    amount = _safe_float(
        _first_non_empty(
            item.get("amount"),
            item.get("value"),
            item.get("quantity"),
            item.get("token_amount"),
        )
    )
    amount_usd = _safe_float(
        _first_non_empty(
            item.get("amount_usd"),
            item.get("usd_value"),
            item.get("value_usd"),
            item.get("amountUsd"),
            item.get("volume_usd"),
        )
    )
    fingerprint = "|".join(
        [
            watched_address,
            str(watcher.blockchain or "ethereum").lower(),
            str(tx_hash or ""),
            str(direction or ""),
            str(token or ""),
            str(counterparty or ""),
            str(occurred_at or ""),
            str(amount or ""),
        ]
    )
    if not any([tx_hash, occurred_at, token, counterparty]):
        return None

    external_id = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()
    return {
        "external_id": external_id,
        "address": watched_address,
        "blockchain": str(watcher.blockchain or "ethereum").lower(),
        "entity_name": watcher.entity_name,
        "label": watcher.label,
        "direction": direction,
        "counterparty_address": counterparty,
        "token": token,
        "amount": amount,
        "amount_usd": amount_usd,
        "tx_hash": tx_hash,
        "occurred_at": occurred_at,
        "source": "surf:wallet-transfers",
        "metadata_json": item,
    }


def _serialize_transfer_event(row: WhaleTransferEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "external_id": row.external_id,
        "address": row.address,
        "blockchain": row.blockchain,
        "entity_name": row.entity_name,
        "label": row.label,
        "direction": row.direction,
        "counterparty_address": row.counterparty_address,
        "token": row.token,
        "amount": row.amount,
        "amount_usd": row.amount_usd,
        "tx_hash": row.tx_hash,
        "occurred_at": row.occurred_at,
        "source": row.source,
        "metadata": row.metadata_json or {},
        "created_at": str(row.created_at) if row.created_at else None,
    }


async def _load_watched_addresses(limit: int | None = None) -> list[MonitoredAddress]:
    if not db_available():
        return []
    capped_limit = min(max(limit or settings.onchain_whale_max_addresses, 1), 200)
    async with async_session() as session:
        stmt = (
            select(MonitoredAddress)
            .where(
                MonitoredAddress.is_active == 1,
                MonitoredAddress.is_whale == 1,
            )
            .order_by(
                MonitoredAddress.alert_threshold.desc().nullslast(),
                MonitoredAddress.created_at.desc(),
            )
            .limit(capped_limit)
        )
        return list((await session.execute(stmt)).scalars().all())


async def _get_or_create_state(session: Any, scope_key: str = GLOBAL_SCOPE) -> WhaleMonitorState:
    existing = (
        await session.execute(
            select(WhaleMonitorState).where(WhaleMonitorState.scope_key == scope_key)
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    state = WhaleMonitorState(scope_key=scope_key, last_status="idle")
    session.add(state)
    await session.flush()
    return state


async def collect_whale_transfer_events(*, force: bool = False) -> dict[str, Any]:
    if not db_available():
        return {
            "db_available": False,
            "status": "skipped",
            "watched_address_count": 0,
            "fetched_transfer_count": 0,
            "stored_event_count": 0,
            "error_count": 0,
            "warning": "Database not available",
        }

    watchers = await _load_watched_addresses()
    if not watchers:
        try:
            from app.address_intel.service import ensure_default_whale_watch_addresses

            ensure_result = await ensure_default_whale_watch_addresses()
            logger.info(
                "Whale watchlist bootstrap: seeded=%s watched=%d",
                ensure_result.get("seeded"),
                ensure_result.get("watched_address_count", 0),
            )
        except Exception:
            logger.debug("Failed to bootstrap whale watchlist", exc_info=True)
        watchers = await _load_watched_addresses()
    started_at = utcnow_naive()
    fetched_transfer_count = 0
    stored_event_count = 0
    skipped_existing_count = 0
    below_threshold_count = 0
    error_count = 0
    processed_addresses: list[str] = []
    warnings: list[str] = []

    async with async_session() as session:
        state = await _get_or_create_state(session)
        state.last_status = "running"
        state.last_run_started_at = started_at
        state.watched_address_count = len(watchers)
        state.metadata_json = {
            "processed_addresses": [],
            "warnings": [],
        }
        await session.commit()

    if not watchers:
        finished_at = utcnow_naive()
        async with async_session() as session:
            state = await _get_or_create_state(session)
            state.last_status = "idle"
            state.last_run_finished_at = finished_at
            state.watched_address_count = 0
            state.fetched_transfer_count = 0
            state.stored_event_count = 0
            state.error_count = 0
            state.metadata_json = {
                "processed_addresses": [],
                "warnings": ["No whale addresses in monitored_addresses"],
            }
            await session.commit()
        return {
            "db_available": True,
            "status": "idle",
            "watched_address_count": 0,
            "fetched_transfer_count": 0,
            "stored_event_count": 0,
            "error_count": 0,
            "warnings": ["No whale addresses in monitored_addresses"],
        }

    async with async_session() as session:
        for watcher in watchers:
            processed_addresses.append(watcher.address)
            threshold = _safe_float(watcher.alert_threshold) or float(settings.onchain_whale_min_usd)
            try:
                transfers = await surf.get_wallet_transfers(
                    watcher.address,
                    watcher.blockchain or "ethereum",
                    settings.onchain_whale_transfer_limit,
                )
            except Exception:
                error_count += 1
                warnings.append(f"Failed to fetch transfers for {watcher.address}")
                logger.debug("Transfer fetch failed for %s", watcher.address, exc_info=True)
                continue

            if not isinstance(transfers, list):
                continue

            for transfer in transfers:
                normalized = _normalize_transfer_item(transfer, watcher)
                if not normalized:
                    continue
                fetched_transfer_count += 1

                if not force and normalized.get("amount_usd") is not None and float(normalized["amount_usd"]) < threshold:
                    below_threshold_count += 1
                    continue

                exists = (
                    await session.execute(
                        select(WhaleTransferEvent.id).where(
                            WhaleTransferEvent.external_id == normalized["external_id"]
                        )
                    )
                ).scalar_one_or_none()
                if exists is not None:
                    skipped_existing_count += 1
                    continue

                event = WhaleTransferEvent(**normalized)
                session.add(event)
                session.add(
                    WhaleAlert(
                        address=normalized["address"],
                        action=normalized.get("direction") or "transfer",
                        amount=float(normalized.get("amount") or 0),
                        token=normalized.get("token") or "UNKNOWN",
                        tx_hash=normalized.get("tx_hash"),
                    )
                )
                stored_event_count += 1

        finished_at = utcnow_naive()
        state = await _get_or_create_state(session)
        state.last_status = "ok" if error_count == 0 else "partial"
        state.last_run_finished_at = finished_at
        state.watched_address_count = len(watchers)
        state.fetched_transfer_count = fetched_transfer_count
        state.stored_event_count = stored_event_count
        state.error_count = error_count
        state.metadata_json = {
            "processed_addresses": processed_addresses,
            "warnings": warnings,
            "skipped_existing_count": skipped_existing_count,
            "below_threshold_count": below_threshold_count,
            "monitor_interval_minutes": settings.onchain_whale_monitor_interval_minutes,
            "min_usd": settings.onchain_whale_min_usd,
        }
        await session.commit()

    result = {
        "db_available": True,
        "status": "ok" if error_count == 0 else "partial",
        "watched_address_count": len(watchers),
        "fetched_transfer_count": fetched_transfer_count,
        "stored_event_count": stored_event_count,
        "skipped_existing_count": skipped_existing_count,
        "below_threshold_count": below_threshold_count,
        "error_count": error_count,
        "processed_addresses": processed_addresses,
        "warnings": warnings,
    }
    logger.info(
        "Whale monitor finished: watched=%d fetched=%d stored=%d skipped=%d errors=%d",
        len(watchers),
        fetched_transfer_count,
        stored_event_count,
        skipped_existing_count,
        error_count,
    )
    return result


async def list_whale_transfer_events(
    *,
    chain: str | None = None,
    address: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    if not db_available():
        return []

    capped_limit = min(max(limit, 1), 200)
    async with async_session() as session:
        stmt = select(WhaleTransferEvent)
        if chain:
            stmt = stmt.where(WhaleTransferEvent.blockchain == chain.lower())
        if address:
            stmt = stmt.where(WhaleTransferEvent.address == address.lower())
        stmt = stmt.order_by(WhaleTransferEvent.created_at.desc()).limit(capped_limit)
        rows = (await session.execute(stmt)).scalars().all()
        return [_serialize_transfer_event(row) for row in rows]


async def get_recent_transactions(min_value: int = 1_000_000, limit: int = 20) -> list[dict[str, Any]]:
    events = await list_whale_transfer_events(limit=limit)
    filtered: list[dict[str, Any]] = []
    for item in events:
        amount_usd = _safe_float(item.get("amount_usd"))
        if amount_usd is None or amount_usd >= float(min_value):
            filtered.append(item)
    return filtered[:limit]


async def get_whale_monitor_status() -> dict[str, Any]:
    watched_addresses = await _load_watched_addresses()
    if not db_available():
        return {
            "db_available": False,
            "status": "unavailable",
            "watched_address_count": 0,
            "event_count": 0,
            "last_run_started_at": None,
            "last_run_finished_at": None,
            "monitor_interval_minutes": settings.onchain_whale_monitor_interval_minutes,
        }

    async with async_session() as session:
        state = (
            await session.execute(
                select(WhaleMonitorState).where(WhaleMonitorState.scope_key == GLOBAL_SCOPE)
            )
        ).scalar_one_or_none()
        event_count = int((await session.execute(select(func.count()).select_from(WhaleTransferEvent))).scalar() or 0)

    metadata = (state.metadata_json if state and isinstance(state.metadata_json, dict) else {}) if state else {}
    return {
        "db_available": True,
        "status": state.last_status if state else "idle",
        "watched_address_count": len(watched_addresses),
        "watched_addresses": [
            {
                "address": row.address,
                "blockchain": row.blockchain,
                "entity_name": row.entity_name,
                "label": row.label,
                "alert_threshold": row.alert_threshold,
            }
            for row in watched_addresses
        ],
        "event_count": event_count,
        "last_run_started_at": str(state.last_run_started_at) if state and state.last_run_started_at else None,
        "last_run_finished_at": str(state.last_run_finished_at) if state and state.last_run_finished_at else None,
        "fetched_transfer_count": state.fetched_transfer_count if state else 0,
        "stored_event_count": state.stored_event_count if state else 0,
        "error_count": state.error_count if state else 0,
        "monitor_interval_minutes": settings.onchain_whale_monitor_interval_minutes,
        "transfer_limit": settings.onchain_whale_transfer_limit,
        "min_usd": settings.onchain_whale_min_usd,
        "metadata": metadata,
    }
