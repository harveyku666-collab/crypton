"""Whale transfer monitoring service."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import func, or_, select

from app.common.database import async_session, db_available
from app.common.models import (
    MonitoredAddress,
    WhaleAlert,
    WhaleMonitorState,
    WhaleNotificationChannel,
    WhaleNotificationDelivery,
    WhaleTransferEvent,
)
from app.config import settings
from app.market import aggregator
from app.market.sources import dexscreener, surf

logger = logging.getLogger("bitinfo.onchain.monitor")

GLOBAL_SCOPE = "global"
DEFAULT_NOTIFICATION_CHANNEL = "default-log"
DEFAULT_NOTIFICATION_MIN_SEVERITY = "medium"
UNKNOWN_TOKEN_SYMBOLS = {"", "COIN", "NATIVE", "TOKEN", "UNKNOWN"}
USD_EQUIVALENT_TOKENS = {
    "USD1",
    "USDB",
    "USDC",
    "USDD",
    "USDE",
    "USDS",
    "USDT",
    "FDUSD",
    "PYUSD",
    "TUSD",
}
SEVERITY_RANKS = {
    "info": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}
DEXSCREENER_CHAIN_ALIASES = {
    "arbitrum": {"arbitrum", "arbitrum-one"},
    "avalanche": {"avax", "avalanche"},
    "base": {"base"},
    "bsc": {"bsc", "bnb", "binance-smart-chain"},
    "ethereum": {"eth", "ethereum"},
    "optimism": {"optimism", "op"},
    "polygon": {"matic", "polygon", "polygon-pos"},
    "solana": {"solana"},
}


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _normalize_severity(value: Any, *, default: str = "high") -> str:
    text = str(value or "").strip().lower()
    if text in SEVERITY_RANKS:
        return text
    return default


def _severity_rank(value: Any) -> int:
    return SEVERITY_RANKS.get(_normalize_severity(value, default="info"), 0)


def classify_whale_alert_severity(
    *,
    amount_usd: float | None,
    threshold: float,
) -> str:
    if amount_usd is None:
        return "low"
    normalized_threshold = max(float(threshold or 0), float(settings.onchain_whale_min_usd), 1.0)
    if amount_usd >= max(normalized_threshold * 10, 10_000_000):
        return "critical"
    if amount_usd >= max(normalized_threshold * 5, 5_000_000):
        return "high"
    if amount_usd >= normalized_threshold:
        return "medium"
    return "low"


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


def _normalize_token_symbol(value: Any) -> str | None:
    text = "".join(ch for ch in str(value or "").upper() if ch.isalnum())
    return text[:24] if text else None


def _extract_nested_value(mapping: dict[str, Any], *paths: tuple[str, ...]) -> Any:
    for path in paths:
        current: Any = mapping
        for key in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)
        if current is not None and current != "":
            return current
    return None


def _extract_token_address(metadata: dict[str, Any] | None) -> str | None:
    payload = metadata if isinstance(metadata, dict) else {}
    value = _extract_nested_value(
        payload,
        ("token_address",),
        ("tokenAddress",),
        ("contract_address",),
        ("contractAddress",),
        ("asset_address",),
        ("assetAddress",),
        ("currency_address",),
        ("currencyAddress",),
        ("token", "address"),
        ("tokenInfo", "address"),
        ("asset", "address"),
        ("coin", "address"),
    )
    text = str(value or "").strip()
    return text or None


def _extract_candidate_symbols(token: Any, metadata: dict[str, Any] | None) -> list[str]:
    payload = metadata if isinstance(metadata, dict) else {}
    values = [
        token,
        payload.get("symbol"),
        payload.get("token_symbol"),
        payload.get("asset_symbol"),
        payload.get("currency"),
        _extract_nested_value(payload, ("token", "symbol")),
        _extract_nested_value(payload, ("tokenInfo", "symbol")),
        _extract_nested_value(payload, ("asset", "symbol")),
        _extract_nested_value(payload, ("baseToken", "symbol")),
        _extract_nested_value(payload, ("coin", "symbol")),
    ]
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        symbol = _normalize_token_symbol(value)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        normalized.append(symbol)
    return normalized


def _is_unknown_token(value: Any) -> bool:
    normalized = _normalize_token_symbol(value) or "UNKNOWN"
    return normalized in UNKNOWN_TOKEN_SYMBOLS


def _transfer_lookup_key(address: Any, tx_hash: Any) -> tuple[str, str] | None:
    normalized_address = str(address or "").strip().lower()
    normalized_tx_hash = str(tx_hash or "").strip().lower()
    if not normalized_address or not normalized_tx_hash:
        return None
    return normalized_address, normalized_tx_hash


def _select_preferred_token(token: Any, metadata: dict[str, Any] | None) -> str | None:
    symbols = _extract_candidate_symbols(token, metadata)
    for symbol in symbols:
        if symbol not in UNKNOWN_TOKEN_SYMBOLS:
            return symbol
    return symbols[0] if symbols else None


def _merge_transfer_event_into_alert(row: WhaleAlert, transfer: WhaleTransferEvent) -> bool:
    changed = False
    transfer_metadata = transfer.metadata_json if isinstance(transfer.metadata_json, dict) else {}
    existing_metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    merged_metadata = {**transfer_metadata, **existing_metadata}
    preferred_token = _select_preferred_token(transfer.token, transfer_metadata)

    if row.event_id is None and transfer.id is not None:
        row.event_id = int(transfer.id)
        changed = True
    if not row.external_id and transfer.external_id:
        row.external_id = transfer.external_id
        changed = True
    if not row.blockchain and transfer.blockchain:
        row.blockchain = transfer.blockchain
        changed = True
    if not row.entity_name and transfer.entity_name:
        row.entity_name = transfer.entity_name
        changed = True
    if not row.label and transfer.label:
        row.label = transfer.label
        changed = True
    if not row.counterparty_address and transfer.counterparty_address:
        row.counterparty_address = transfer.counterparty_address
        changed = True
    if (row.amount in {None, 0}) and transfer.amount not in {None, 0}:
        row.amount = float(transfer.amount or 0)
        changed = True
    if row.amount_usd is None and transfer.amount_usd is not None:
        row.amount_usd = float(transfer.amount_usd)
        changed = True
    if preferred_token and (not row.token or _is_unknown_token(row.token)):
        row.token = preferred_token
        changed = True
    if merged_metadata != existing_metadata:
        row.metadata_json = merged_metadata
        changed = True

    return changed


def _match_dexscreener_chain(blockchain: Any, chain: Any) -> bool:
    normalized_blockchain = str(blockchain or "").strip().lower()
    normalized_chain = str(chain or "").strip().lower()
    if not normalized_blockchain or not normalized_chain:
        return False
    allowed = DEXSCREENER_CHAIN_ALIASES.get(normalized_blockchain, {normalized_blockchain})
    return normalized_chain in allowed


def _pick_best_dex_pair(
    pairs: list[dict[str, Any]],
    *,
    blockchain: str | None,
    symbols: list[str],
) -> dict[str, Any] | None:
    filtered: list[dict[str, Any]] = []
    normalized_symbols = set(symbols)
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        price_usd = _safe_float(pair.get("price_usd"))
        if price_usd is None or price_usd <= 0:
            continue
        base_symbol = _normalize_token_symbol(((pair.get("base_token") or {}).get("symbol")))
        if normalized_symbols and base_symbol and base_symbol not in normalized_symbols:
            continue
        filtered.append(pair)

    if not filtered:
        return None

    chain_matched = [pair for pair in filtered if _match_dexscreener_chain(blockchain, pair.get("chain"))]
    ranked = chain_matched or filtered
    ranked.sort(
        key=lambda pair: (
            _safe_float(pair.get("liquidity_usd")) or 0.0,
            _safe_float(pair.get("volume_24h")) or 0.0,
        ),
        reverse=True,
    )
    return ranked[0] if ranked else None


async def _estimate_market_amount_usd(
    *,
    token: Any,
    amount: Any,
    amount_usd: Any,
    blockchain: str | None,
    metadata: dict[str, Any] | None,
) -> tuple[float | None, str | None]:
    normalized_amount_usd = _safe_float(amount_usd)
    if normalized_amount_usd is not None:
        return normalized_amount_usd, None

    payload = metadata if isinstance(metadata, dict) else {}
    direct_amount_usd = _safe_float(
        _extract_nested_value(
            payload,
            ("amount_usd",),
            ("usd_value",),
            ("value_usd",),
            ("amountUsd",),
            ("volume_usd",),
            ("quote_amount_usd",),
            ("price", "usd"),
        )
    )
    if direct_amount_usd is not None:
        return direct_amount_usd, "metadata"

    normalized_amount = _safe_float(amount)
    if normalized_amount is None or normalized_amount <= 0:
        return None, None

    symbols = _extract_candidate_symbols(token, payload)
    for symbol in symbols:
        if symbol in USD_EQUIVALENT_TOKENS:
            return normalized_amount, "stablecoin_parity"

    token_address = _extract_token_address(payload)
    if token_address:
        try:
            pairs = await dexscreener.get_token_pairs(token_address, limit=20)
        except Exception:
            logger.debug("DEX Screener valuation lookup failed for %s", token_address, exc_info=True)
            pairs = []
        pair = _pick_best_dex_pair(pairs, blockchain=blockchain, symbols=symbols)
        if pair is not None:
            price_usd = _safe_float(pair.get("price_usd"))
            if price_usd is not None and price_usd > 0:
                return normalized_amount * price_usd, "dexscreener"

    for symbol in symbols:
        if symbol in UNKNOWN_TOKEN_SYMBOLS:
            continue
        try:
            snapshot = await aggregator.get_symbol_price(symbol)
        except Exception:
            logger.debug("Market valuation lookup failed for %s", symbol, exc_info=True)
            snapshot = None
        price = _safe_float((snapshot or {}).get("price")) if isinstance(snapshot, dict) else None
        if price is not None and price > 0:
            source = str(snapshot.get("source") or "market") if isinstance(snapshot, dict) else "market"
            return normalized_amount * price, source

    return None, None


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


def _serialize_whale_alert(row: WhaleAlert) -> dict[str, Any]:
    return {
        "id": row.id,
        "external_id": row.external_id,
        "event_id": row.event_id,
        "address": row.address,
        "blockchain": row.blockchain,
        "entity_name": row.entity_name,
        "label": row.label,
        "action": row.action,
        "amount": row.amount,
        "amount_usd": row.amount_usd,
        "token": row.token,
        "tx_hash": row.tx_hash,
        "counterparty_address": row.counterparty_address,
        "severity": row.severity,
        "notification_status": row.notification_status,
        "metadata": row.metadata_json or {},
        "created_at": str(row.created_at) if row.created_at else None,
    }


def _serialize_notification_channel(row: WhaleNotificationChannel) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "channel_type": row.channel_type,
        "target": row.target,
        "min_severity": row.min_severity,
        "is_active": bool(row.is_active),
        "metadata": row.metadata_json or {},
        "created_at": str(row.created_at) if row.created_at else None,
    }


def _serialize_notification_delivery(row: WhaleNotificationDelivery) -> dict[str, Any]:
    return {
        "id": row.id,
        "alert_id": row.alert_id,
        "channel_id": row.channel_id,
        "delivery_status": row.delivery_status,
        "response_code": row.response_code,
        "error_message": row.error_message,
        "payload": row.payload_json or {},
        "created_at": str(row.created_at) if row.created_at else None,
    }


def _severity_matches(alert_severity: str, min_severity: str) -> bool:
    return _severity_rank(alert_severity) >= _severity_rank(min_severity)


def _build_alert_payload(alert: dict[str, Any], channel: WhaleNotificationChannel) -> dict[str, Any]:
    return {
        "type": "whale_alert",
        "severity": alert.get("severity"),
        "channel": {
            "name": channel.name,
            "type": channel.channel_type,
        },
        "alert": alert,
    }


def _build_log_message(alert: dict[str, Any]) -> str:
    amount_usd = _safe_float(alert.get("amount_usd"))
    if amount_usd is not None:
        amount_text = f"${amount_usd:,.2f}"
    else:
        amount_text = str(alert.get("amount") or "unknown")
    token = alert.get("token") or "UNKNOWN"
    entity = alert.get("entity_name") or alert.get("label") or alert.get("address") or "unknown"
    action = alert.get("action") or "transfer"
    severity = str(alert.get("severity") or "info").upper()
    return f"[{severity}] whale alert: {entity} {action} {amount_text} {token}"


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


async def ensure_default_notification_channels() -> dict[str, Any]:
    if not db_available():
        return {"created": 0, "count": 0, "warning": "Database not available"}

    created = 0
    updated = 0
    async with async_session() as session:
        existing = (
            await session.execute(
                select(WhaleNotificationChannel).where(
                    WhaleNotificationChannel.name == DEFAULT_NOTIFICATION_CHANNEL
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            session.add(
                WhaleNotificationChannel(
                    name=DEFAULT_NOTIFICATION_CHANNEL,
                    channel_type="log",
                    target="bitinfo.onchain.alerts",
                    min_severity=DEFAULT_NOTIFICATION_MIN_SEVERITY,
                    is_active=1,
                    metadata_json={"auto_created": True},
                )
            )
            created = 1
        else:
            metadata = existing.metadata_json if isinstance(existing.metadata_json, dict) else {}
            if metadata.get("auto_created"):
                changed = False
                normalized_min_severity = _normalize_severity(
                    existing.min_severity,
                    default=DEFAULT_NOTIFICATION_MIN_SEVERITY,
                )
                if existing.channel_type != "log":
                    existing.channel_type = "log"
                    changed = True
                if existing.target != "bitinfo.onchain.alerts":
                    existing.target = "bitinfo.onchain.alerts"
                    changed = True
                if normalized_min_severity != DEFAULT_NOTIFICATION_MIN_SEVERITY:
                    existing.min_severity = DEFAULT_NOTIFICATION_MIN_SEVERITY
                    changed = True
                if int(existing.is_active or 0) != 1:
                    existing.is_active = 1
                    changed = True
                if metadata.get("auto_created") is not True:
                    existing.metadata_json = {**metadata, "auto_created": True}
                    changed = True
                if changed:
                    updated = 1

        await session.commit()
        active_count = int(
            (
                await session.execute(
                    select(func.count()).select_from(WhaleNotificationChannel).where(
                        WhaleNotificationChannel.is_active == 1
                    )
                )
            ).scalar()
            or 0
        )
    return {"created": created, "updated": updated, "count": active_count}


async def _load_active_notification_channels() -> list[WhaleNotificationChannel]:
    if not db_available():
        return []
    async with async_session() as session:
        stmt = (
            select(WhaleNotificationChannel)
            .where(WhaleNotificationChannel.is_active == 1)
            .order_by(WhaleNotificationChannel.created_at.asc())
        )
        return list((await session.execute(stmt)).scalars().all())


async def upsert_whale_notification_channels(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not db_available():
        raise RuntimeError("Database not available")

    created = 0
    updated = 0
    async with async_session() as session:
        for row in rows:
            name = str(row.get("name") or "").strip()
            channel_type = str(row.get("channel_type") or "").strip().lower()
            target = str(row.get("target") or "").strip()
            if not name or channel_type not in {"log", "webhook"} or not target:
                continue
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            existing = (
                await session.execute(
                    select(WhaleNotificationChannel).where(WhaleNotificationChannel.name == name)
                )
            ).scalar_one_or_none()
            payload = {
                "channel_type": channel_type,
                "target": target,
                "min_severity": _normalize_severity(
                    row.get("min_severity"),
                    default=DEFAULT_NOTIFICATION_MIN_SEVERITY,
                ),
                "is_active": 1 if row.get("is_active", True) else 0,
                "metadata_json": metadata,
            }
            if existing is None:
                session.add(WhaleNotificationChannel(name=name, **payload))
                created += 1
            else:
                existing.channel_type = payload["channel_type"]
                existing.target = payload["target"]
                existing.min_severity = payload["min_severity"]
                existing.is_active = payload["is_active"]
                existing.metadata_json = payload["metadata_json"]
                updated += 1
        await session.commit()

    return {"count": created + updated, "created": created, "updated": updated}


async def list_whale_notification_channels() -> list[dict[str, Any]]:
    if not db_available():
        return []
    await ensure_default_notification_channels()
    async with async_session() as session:
        stmt = select(WhaleNotificationChannel).order_by(
            WhaleNotificationChannel.is_active.desc(),
            WhaleNotificationChannel.created_at.asc(),
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [_serialize_notification_channel(row) for row in rows]


async def list_whale_alerts(
    *,
    severity: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    if not db_available():
        return []

    capped_limit = min(max(limit, 1), 200)
    async with async_session() as session:
        stmt = select(WhaleAlert)
        if severity:
            stmt = stmt.where(WhaleAlert.severity == _normalize_severity(severity, default="medium"))
        stmt = stmt.order_by(WhaleAlert.created_at.desc()).limit(capped_limit)
        rows = (await session.execute(stmt)).scalars().all()
        return [_serialize_whale_alert(row) for row in rows]


async def list_whale_notification_deliveries(
    *,
    delivery_status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    if not db_available():
        return []

    capped_limit = min(max(limit, 1), 200)
    async with async_session() as session:
        stmt = select(WhaleNotificationDelivery)
        if delivery_status:
            stmt = stmt.where(WhaleNotificationDelivery.delivery_status == str(delivery_status).strip().lower())
        stmt = stmt.order_by(WhaleNotificationDelivery.created_at.desc()).limit(capped_limit)
        rows = (await session.execute(stmt)).scalars().all()
        return [_serialize_notification_delivery(row) for row in rows]


def _normalize_alert_ids(values: list[int] | None) -> list[int]:
    normalized: list[int] = []
    seen: set[int] = set()
    for value in values or []:
        try:
            alert_id = int(value)
        except Exception:
            continue
        if alert_id <= 0 or alert_id in seen:
            continue
        seen.add(alert_id)
        normalized.append(alert_id)
    return normalized


def _infer_legacy_alert_amount_usd(
    *,
    token: Any,
    amount: Any,
    amount_usd: Any,
    threshold: float,
) -> float | None:
    normalized_amount_usd = _safe_float(amount_usd)
    if normalized_amount_usd is not None:
        return normalized_amount_usd

    normalized_amount = _safe_float(amount)
    if normalized_amount is None:
        return None

    normalized_token = str(token or "").strip().upper()
    if normalized_token in USD_EQUIVALENT_TOKENS:
        return normalized_amount
    if normalized_token in {"", "UNKNOWN"} and normalized_amount >= threshold:
        return normalized_amount
    return None


async def _backfill_legacy_whale_alerts(session: Any, rows: list[WhaleAlert]) -> int:
    if not rows:
        return 0

    watch_map: dict[str, MonitoredAddress] = {}
    transfer_map: dict[tuple[str, str], WhaleTransferEvent] = {}
    addresses = sorted(
        {
            str(row.address or "").strip().lower()
            for row in rows
            if str(row.address or "").strip()
        }
    )
    tx_hashes = sorted(
        {
            str(row.tx_hash or "").strip().lower()
            for row in rows
            if str(row.tx_hash or "").strip()
        }
    )
    if addresses:
        watch_rows = (
            await session.execute(
                select(MonitoredAddress).where(MonitoredAddress.address.in_(addresses))
            )
        ).scalars().all()
        watch_map = {
            str(item.address or "").strip().lower(): item
            for item in watch_rows
            if str(item.address or "").strip()
        }
    if addresses and tx_hashes:
        transfer_rows = (
            await session.execute(
                select(WhaleTransferEvent).where(
                    WhaleTransferEvent.address.in_(addresses),
                    WhaleTransferEvent.tx_hash.in_(tx_hashes),
                )
            )
        ).scalars().all()
        for item in transfer_rows:
            key = _transfer_lookup_key(item.address, item.tx_hash)
            if key is None:
                continue
            current = transfer_map.get(key)
            if current is None or str(item.created_at or "") > str(current.created_at or ""):
                transfer_map[key] = item

    updated_count = 0
    for row in rows:
        changed = False
        watcher = watch_map.get(str(row.address or "").strip().lower())
        threshold = _safe_float(watcher.alert_threshold if watcher else None) or float(settings.onchain_whale_min_usd)
        transfer = transfer_map.get(_transfer_lookup_key(row.address, row.tx_hash) or ("", ""))

        if watcher:
            if not row.blockchain and watcher.blockchain:
                row.blockchain = watcher.blockchain
                changed = True
            if not row.entity_name and watcher.entity_name:
                row.entity_name = watcher.entity_name
                changed = True
            if not row.label and watcher.label:
                row.label = watcher.label
                changed = True
        if transfer and _merge_transfer_event_into_alert(row, transfer):
            changed = True

        estimated_amount_usd, valuation_source = await _estimate_market_amount_usd(
            token=row.token,
            amount=row.amount,
            amount_usd=row.amount_usd,
            blockchain=row.blockchain or (watcher.blockchain if watcher else None),
            metadata=row.metadata_json if isinstance(row.metadata_json, dict) else None,
        )
        inferred_amount_usd = estimated_amount_usd
        if inferred_amount_usd is None:
            inferred_amount_usd = _infer_legacy_alert_amount_usd(
                token=row.token,
                amount=row.amount,
                amount_usd=row.amount_usd,
                threshold=threshold,
            )
        if row.amount_usd is None and inferred_amount_usd is not None:
            row.amount_usd = inferred_amount_usd
            changed = True
            metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
            if valuation_source:
                row.metadata_json = {
                    **metadata,
                    "amount_usd_estimated": inferred_amount_usd,
                    "amount_usd_source": valuation_source,
                }
                changed = True

        if not row.severity:
            severity_basis = _safe_float(row.amount_usd)
            if severity_basis is None:
                severity_basis = inferred_amount_usd
            if severity_basis is not None:
                row.severity = classify_whale_alert_severity(
                    amount_usd=severity_basis,
                    threshold=threshold,
                )
                changed = True

        if not row.notification_status:
            row.notification_status = "pending"
            changed = True

        if changed:
            updated_count += 1

    return updated_count


async def replay_whale_alert_notifications(
    *,
    alert_ids: list[int] | None = None,
    severity: str | None = None,
    limit: int = 20,
    only_unsent: bool = True,
) -> dict[str, Any]:
    if not db_available():
        return {
            "db_available": False,
            "status": "skipped",
            "count": 0,
            "warning": "Database not available",
        }

    capped_limit = min(max(limit, 1), 200)
    normalized_ids = _normalize_alert_ids(alert_ids)
    normalized_severity = _normalize_severity(severity, default="medium") if severity else None

    async with async_session() as session:
        stmt = select(WhaleAlert)
        if normalized_ids:
            stmt = stmt.where(WhaleAlert.id.in_(normalized_ids))
        if normalized_severity:
            stmt = stmt.where(WhaleAlert.severity == normalized_severity)
        if only_unsent:
            stmt = stmt.where(
                or_(
                    WhaleAlert.notification_status.is_(None),
                    WhaleAlert.notification_status.in_(("pending", "failed", "skipped")),
                )
            )
        stmt = stmt.order_by(WhaleAlert.created_at.desc(), WhaleAlert.id.desc())
        if not normalized_ids:
            stmt = stmt.limit(capped_limit)
        rows = (await session.execute(stmt)).scalars().all()
        backfilled_count = await _backfill_legacy_whale_alerts(session, rows)
        if backfilled_count > 0:
            await session.commit()
        alerts = [_serialize_whale_alert(row) for row in rows]

    if not alerts:
        return {
            "db_available": True,
            "status": "ok",
            "count": 0,
            "backfilled_count": 0,
            "selected_alert_ids": [],
            "severity": normalized_severity,
            "only_unsent": only_unsent,
            "notification": {
                "alert_count": 0,
                "matched_channel_count": 0,
                "delivery_count": 0,
                "sent_count": 0,
                "failed_count": 0,
            },
            "warning": "No matching whale alerts",
        }

    notification_result = await _notify_alerts(alerts)
    return {
        "db_available": True,
        "status": "ok",
        "count": len(alerts),
        "backfilled_count": backfilled_count,
        "selected_alert_ids": [int(alert["id"]) for alert in alerts if alert.get("id") is not None],
        "severity": normalized_severity,
        "only_unsent": only_unsent,
        "notification": notification_result,
    }


async def _deliver_notification(
    channel: WhaleNotificationChannel,
    payload: dict[str, Any],
) -> dict[str, Any]:
    channel_type = str(channel.channel_type or "").strip().lower()
    if channel_type == "log":
        logger.warning(_build_log_message(payload.get("alert") or {}))
        return {
            "delivery_status": "sent",
            "response_code": None,
            "error_message": None,
            "payload_json": payload,
        }

    if channel_type == "webhook":
        headers = {}
        metadata = channel.metadata_json if isinstance(channel.metadata_json, dict) else {}
        if isinstance(metadata.get("headers"), dict):
            headers = {str(key): str(value) for key, value in metadata["headers"].items()}
        timeout = max(3, int(settings.onchain_whale_notify_timeout_seconds))
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                resp = await client.post(channel.target, json=payload, headers=headers)
            if 200 <= resp.status_code < 300:
                return {
                    "delivery_status": "sent",
                    "response_code": resp.status_code,
                    "error_message": None,
                    "payload_json": payload,
                }
            return {
                "delivery_status": "failed",
                "response_code": resp.status_code,
                "error_message": f"Webhook returned {resp.status_code}",
                "payload_json": payload,
            }
        except Exception as exc:
            return {
                "delivery_status": "failed",
                "response_code": None,
                "error_message": str(exc),
                "payload_json": payload,
            }

    return {
        "delivery_status": "failed",
        "response_code": None,
        "error_message": f"Unsupported channel type: {channel_type}",
        "payload_json": payload,
    }


async def _notify_alerts(alerts: list[dict[str, Any]]) -> dict[str, Any]:
    if not alerts or not db_available():
        return {
            "alert_count": len(alerts),
            "matched_channel_count": 0,
            "delivery_count": 0,
            "sent_count": 0,
            "failed_count": 0,
        }

    await ensure_default_notification_channels()
    channels = await _load_active_notification_channels()

    matched_channel_count = 0
    delivery_count = 0
    sent_count = 0
    failed_count = 0
    deliveries_to_store: list[dict[str, Any]] = []
    alert_status_map: dict[int, str] = {}

    for alert in alerts:
        alert_id = int(alert.get("id") or 0)
        matched_for_alert = 0
        sent_for_alert = 0
        failed_for_alert = 0
        for channel in channels:
            if not _severity_matches(
                str(alert.get("severity") or "low"),
                str(channel.min_severity or DEFAULT_NOTIFICATION_MIN_SEVERITY),
            ):
                continue
            matched_channel_count += 1
            matched_for_alert += 1
            payload = _build_alert_payload(alert, channel)
            result = await _deliver_notification(channel, payload)
            delivery_count += 1
            if result["delivery_status"] == "sent":
                sent_count += 1
                sent_for_alert += 1
            else:
                failed_count += 1
                failed_for_alert += 1
            deliveries_to_store.append(
                {
                    "alert_id": alert_id,
                    "channel_id": channel.id,
                    **result,
                }
            )

        if matched_for_alert == 0:
            alert_status_map[alert_id] = "skipped"
        elif sent_for_alert > 0 and failed_for_alert == 0:
            alert_status_map[alert_id] = "sent"
        elif sent_for_alert > 0:
            alert_status_map[alert_id] = "partial"
        else:
            alert_status_map[alert_id] = "failed"

    async with async_session() as session:
        for delivery in deliveries_to_store:
            session.add(WhaleNotificationDelivery(**delivery))
        if alert_status_map:
            rows = (
                await session.execute(select(WhaleAlert).where(WhaleAlert.id.in_(list(alert_status_map.keys()))))
            ).scalars().all()
            for row in rows:
                row.notification_status = alert_status_map.get(int(row.id), row.notification_status)
        await session.commit()

    return {
        "alert_count": len(alerts),
        "matched_channel_count": matched_channel_count,
        "delivery_count": delivery_count,
        "sent_count": sent_count,
        "failed_count": failed_count,
    }


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
    alert_count = 0
    processed_addresses: list[str] = []
    warnings: list[str] = []
    new_alerts: list[dict[str, Any]] = []

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
                estimated_amount_usd, valuation_source = await _estimate_market_amount_usd(
                    token=normalized.get("token"),
                    amount=normalized.get("amount"),
                    amount_usd=normalized.get("amount_usd"),
                    blockchain=normalized.get("blockchain"),
                    metadata=normalized.get("metadata_json") if isinstance(normalized.get("metadata_json"), dict) else None,
                )
                if normalized.get("amount_usd") is None and estimated_amount_usd is not None:
                    normalized["amount_usd"] = estimated_amount_usd
                    metadata = normalized.get("metadata_json") if isinstance(normalized.get("metadata_json"), dict) else {}
                    if valuation_source:
                        normalized["metadata_json"] = {
                            **metadata,
                            "amount_usd_estimated": estimated_amount_usd,
                            "amount_usd_source": valuation_source,
                        }
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
                await session.flush()
                severity = classify_whale_alert_severity(
                    amount_usd=_safe_float(normalized.get("amount_usd")),
                    threshold=threshold,
                )
                alert = WhaleAlert(
                    external_id=normalized.get("external_id"),
                    event_id=event.id,
                    address=normalized["address"],
                    blockchain=normalized.get("blockchain"),
                    entity_name=normalized.get("entity_name"),
                    label=normalized.get("label"),
                    action=normalized.get("direction") or "transfer",
                    amount=float(normalized.get("amount") or 0),
                    amount_usd=_safe_float(normalized.get("amount_usd")),
                    token=normalized.get("token") or "UNKNOWN",
                    tx_hash=normalized.get("tx_hash"),
                    counterparty_address=normalized.get("counterparty_address"),
                    severity=severity,
                    notification_status="pending",
                    metadata_json={
                        "source": normalized.get("source"),
                        "occurred_at": normalized.get("occurred_at"),
                    },
                )
                session.add(alert)
                await session.flush()
                new_alerts.append(_serialize_whale_alert(alert))
                alert_count += 1
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
            "alert_count": alert_count,
        }
        await session.commit()

    notification_result = await _notify_alerts(new_alerts)

    async with async_session() as session:
        state = await _get_or_create_state(session)
        metadata = state.metadata_json if isinstance(state.metadata_json, dict) else {}
        metadata.update(
            {
                "alert_count": alert_count,
                "matched_channel_count": notification_result.get("matched_channel_count", 0),
                "delivery_count": notification_result.get("delivery_count", 0),
                "sent_count": notification_result.get("sent_count", 0),
                "failed_delivery_count": notification_result.get("failed_count", 0),
            }
        )
        state.metadata_json = metadata
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
        "alert_count": alert_count,
        "processed_addresses": processed_addresses,
        "warnings": warnings,
        "notification": notification_result,
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

    await ensure_default_notification_channels()
    async with async_session() as session:
        state = (
            await session.execute(
                select(WhaleMonitorState).where(WhaleMonitorState.scope_key == GLOBAL_SCOPE)
            )
        ).scalar_one_or_none()
        event_count = int((await session.execute(select(func.count()).select_from(WhaleTransferEvent))).scalar() or 0)
        alert_count = int((await session.execute(select(func.count()).select_from(WhaleAlert))).scalar() or 0)
        channel_count = int((await session.execute(select(func.count()).select_from(WhaleNotificationChannel))).scalar() or 0)
        delivery_count = int((await session.execute(select(func.count()).select_from(WhaleNotificationDelivery))).scalar() or 0)

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
        "alert_count": alert_count,
        "channel_count": channel_count,
        "delivery_count": delivery_count,
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
