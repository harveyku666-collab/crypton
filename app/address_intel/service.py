"""Address intelligence service for exchanges, institutions, and whale wallets."""

from __future__ import annotations

import asyncio
import re
from typing import Any, Iterable

from sqlalchemy import and_, func, or_, select

from app.address_intel.legacy_store import (
    build_freshness_status,
    fetch_activity_profile_by_name,
    fetch_legacy_catalog,
    fetch_legacy_overview,
    fetch_registry_entity_by_address,
    fetch_registry_watch_addresses,
)
from app.address_intel.seeds import get_default_monitored_address_seeds
from app.common.cache import cached
from app.common.database import async_session, db_available
from app.common.models import MonitoredAddress
from app.market.sources import surf

ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")

EXCHANGE_KEYWORDS = {
    "exchange", "binance", "coinbase", "okx", "kraken", "bybit",
    "gate", "gateio", "mexc", "kucoin", "bitget", "huobi", "cex",
}
INSTITUTION_KEYWORDS = {
    "fund", "capital", "ventures", "foundation", "treasury", "institution",
    "asset management", "grayscale", "blackrock", "fidelity", "jump", "wintermute",
    "galaxy", "multicoin", "dragonfly", "a16z", "pantera", "hashkey",
}
WHALE_KEYWORDS = {"whale", "smart money", "smartmoney", "top holder", "high net worth", "og"}


def _safe_float(value: Any) -> float | None:
    try:
        if value in {None, ""}:
            return None
        return float(value)
    except Exception:
        return None


def _is_address(value: str | None) -> bool:
    return bool(value and ADDRESS_RE.match(value.strip()))


def normalize_address(address: str | None) -> str | None:
    raw = str(address or "").strip()
    if not raw:
        return None
    if _is_address(raw):
        return raw.lower()
    return raw


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _flatten_text(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    parts: list[str] = []
    for key in (
        "label", "name", "title", "entity_name", "entity", "category", "type",
        "description", "summary", "wallet_name", "owner", "source", "address_type",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip().lower())
    return " ".join(parts)


def infer_address_type(payload: dict[str, Any] | None, fallback: str | None = None) -> str:
    explicit = str((payload or {}).get("address_type") or fallback or "").strip().lower()
    if explicit in {"exchange", "institution", "whale", "fund", "market-maker", "smart-money"}:
        return explicit

    haystack = _flatten_text(payload)
    if any(keyword in haystack for keyword in EXCHANGE_KEYWORDS):
        return "exchange"
    if any(keyword in haystack for keyword in INSTITUTION_KEYWORDS):
        return "institution"
    if any(keyword in haystack for keyword in WHALE_KEYWORDS):
        return "whale"
    return explicit or "unknown"


def infer_is_whale(payload: dict[str, Any] | None, address_type: str | None = None) -> bool:
    if not isinstance(payload, dict):
        return address_type == "whale"
    if payload.get("is_whale") in {True, 1, "1", "true", "True"}:
        return True
    if address_type == "whale":
        return True
    haystack = _flatten_text(payload)
    if any(keyword in haystack for keyword in WHALE_KEYWORDS):
        return True
    for key in ("net_worth_usd", "balance_usd", "usd_value", "value_usd", "portfolio_value"):
        value = _safe_float(payload.get(key))
        if value and value >= 1_000_000:
            return True
    return False


def _extract_address(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("address", "wallet_address", "wallet", "owner_address", "account"):
        value = normalize_address(payload.get(key))
        if value:
            return value
    return None


def _extract_chain(payload: dict[str, Any] | None, fallback: str = "ethereum") -> str:
    if not isinstance(payload, dict):
        return fallback
    raw = _first_non_empty(payload.get("blockchain"), payload.get("chain"), fallback) or fallback
    return raw.lower()


def _normalize_entity(
    payload: dict[str, Any],
    *,
    source: str,
    default_chain: str = "ethereum",
) -> dict[str, Any]:
    address = _extract_address(payload)
    address_type = infer_address_type(payload)
    is_whale = infer_is_whale(payload, address_type=address_type)
    label = _first_non_empty(
        payload.get("label"),
        payload.get("name"),
        payload.get("title"),
        payload.get("wallet_name"),
        payload.get("entity"),
    )
    entity_name = _first_non_empty(
        payload.get("entity_name"),
        payload.get("name"),
        payload.get("label"),
        payload.get("title"),
    )
    score = _safe_float(payload.get("score") or payload.get("confidence") or payload.get("weight"))
    return {
        "address": address,
        "blockchain": _extract_chain(payload, fallback=default_chain),
        "label": label,
        "entity_name": entity_name or label,
        "address_type": address_type,
        "is_whale": bool(is_whale),
        "score": score,
        "source": source,
        "metadata": payload,
    }


def _serialize_monitored(row: MonitoredAddress) -> dict[str, Any]:
    return {
        "id": row.id,
        "address": row.address,
        "blockchain": row.blockchain,
        "label": row.label,
        "entity_name": row.entity_name,
        "address_type": row.address_type or "unknown",
        "is_whale": bool(row.is_whale),
        "alert_threshold": row.alert_threshold,
        "source": row.source,
        "is_active": bool(row.is_active),
        "metadata": row.metadata_json or {},
        "created_at": str(row.created_at) if row.created_at else None,
    }


def _dedupe_entities(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        key = item.get("address") or item.get("entity_name") or item.get("label")
        if not key:
            continue
        normalized_key = str(key).strip().lower()
        if normalized_key in seen:
            continue
        seen.add(normalized_key)
        deduped.append(item)
    return deduped


def _sort_entities(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _sort_key(item: dict[str, Any]) -> tuple[int, int, float, str]:
        entity_type = str(item.get("address_type") or "unknown")
        type_rank = {"exchange": 0, "institution": 1, "whale": 2}.get(entity_type, 9)
        address_bonus = 0 if item.get("address") else 1
        score = float(item.get("score") or 0)
        name = str(item.get("entity_name") or item.get("label") or "")
        return (type_rank, address_bonus, -score, name.lower())

    return sorted(items, key=_sort_key)


async def _search_surf_entities(
    query: str,
    *,
    chain: str,
    limit: int,
) -> list[dict[str, Any]]:
    wallet_task = surf.search_wallet(query, limit)
    fund_task = surf.search_fund(query, min(limit, 20))
    wallet_rows, fund_rows = await asyncio.gather(wallet_task, fund_task, return_exceptions=True)

    items: list[dict[str, Any]] = []
    if isinstance(wallet_rows, list):
        items.extend(
            _normalize_entity(item, source="surf:wallet-search", default_chain=chain)
            for item in wallet_rows
            if isinstance(item, dict)
        )
    if isinstance(fund_rows, list):
        items.extend(
            _normalize_entity(
                {**item, "address_type": "institution"},
                source="surf:fund-search",
                default_chain=chain,
            )
            for item in fund_rows
            if isinstance(item, dict)
        )
    return _sort_entities(_dedupe_entities(items))[:limit]


async def _classify_surf_addresses(
    addresses: list[str],
    *,
    chain: str,
) -> list[dict[str, Any]]:
    if not addresses:
        return []

    labels = await surf.get_wallet_labels_batch(addresses)
    label_map: dict[str, dict[str, Any]] = {}
    if isinstance(labels, list):
        for item in labels:
            if not isinstance(item, dict):
                continue
            address = normalize_address(_extract_address(item))
            if address:
                label_map[address] = item

    return [
        _normalize_entity(
            {
                "address": address,
                "blockchain": chain,
                **(label_map.get(address) or {}),
            },
            source="surf:wallet-labels",
            default_chain=chain,
        )
        for address in addresses
    ]


async def search_address_entities(
    q: str,
    *,
    chain: str = "ethereum",
    entity_type: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    query = str(q or "").strip()
    if not query:
        return []
    if _is_address(query):
        return await classify_addresses([query], chain=chain, persist=False)

    search_limit = min(max(limit, 1), 50)
    legacy_items = await fetch_legacy_catalog(
        q=query,
        chain=chain,
        entity_type=entity_type,
        limit=search_limit,
    )
    surf_items: list[dict[str, Any]] = []
    if len(legacy_items) < search_limit:
        surf_items = await _search_surf_entities(query, chain=chain, limit=search_limit)
    filtered = _sort_entities(_dedupe_entities([*legacy_items, *surf_items]))
    if entity_type:
        filtered = [item for item in filtered if item.get("address_type") == entity_type]
    return filtered[:search_limit]


async def classify_addresses(
    addresses: Iterable[str],
    *,
    chain: str = "ethereum",
    persist: bool = False,
) -> list[dict[str, Any]]:
    normalized = [normalize_address(address) for address in addresses]
    picked = [address for address in normalized if address][:50]
    if not picked:
        return []

    legacy_results_raw = await asyncio.gather(
        *(fetch_registry_entity_by_address(address) for address in picked),
        return_exceptions=True,
    )
    legacy_map: dict[str, dict[str, Any]] = {}
    for item in legacy_results_raw:
        if isinstance(item, dict) and item.get("address"):
            legacy_map[str(item["address"]).lower()] = item

    missing = [address for address in picked if address not in legacy_map]
    surf_results = await _classify_surf_addresses(missing, chain=chain)
    surf_map = {
        str(item.get("address") or "").lower(): item
        for item in surf_results
        if item.get("address")
    }

    results = [legacy_map.get(address) or surf_map.get(address) for address in picked]
    results = [item for item in results if isinstance(item, dict)]

    if persist:
        await bulk_upsert_monitored_addresses(results)
    return results


async def get_address_profile(
    address: str,
    *,
    chain: str = "ethereum",
    history_limit: int = 10,
    transfer_limit: int = 10,
    time_range: str = "30d",
) -> dict[str, Any]:
    normalized = normalize_address(address)
    if not normalized:
        return {"error": "Invalid address"}

    legacy_entity = await fetch_registry_entity_by_address(normalized)
    if legacy_entity:
        activity_profile = await fetch_activity_profile_by_name(
            str(legacy_entity.get("entity_name") or ""),
            history_limit=history_limit,
            transfer_limit=transfer_limit,
        )
        summary = dict((activity_profile or {}).get("summary") or {})
        if not summary:
            summary = {
                "history_count": 0,
                "transfer_count": 0,
                "net_worth_points": 0,
                "latest_net_worth": None,
                "freshness": build_freshness_status(),
            }

        latest_worth = summary.get("latest_net_worth")
        wallet_detail = {
            "data_mode": "legacy",
            "description": ((legacy_entity.get("metadata") or {}).get("description")),
            "category": ((legacy_entity.get("metadata") or {}).get("category")),
            "confidence_score": legacy_entity.get("score"),
            "source": legacy_entity.get("source"),
            "balance_usd": (latest_worth or {}).get("usd_value"),
            "legacy_source": ((legacy_entity.get("metadata") or {}).get("legacy_source")),
        }
        return {
            "entity": legacy_entity,
            "wallet_detail": wallet_detail,
            "history": (activity_profile or {}).get("history", []),
            "transfers": (activity_profile or {}).get("transfers", []),
            "net_worth": [latest_worth] if latest_worth else [],
            "summary": {
                **summary,
                "source_mode": "legacy",
            },
            "movement_events": (activity_profile or {}).get("movement_events", []),
            "daily_focus": (activity_profile or {}).get("daily_focus", []),
            "weekly_summaries": (activity_profile or {}).get("weekly_summaries", []),
        }

    labels_task = classify_addresses([normalized], chain=chain, persist=False)
    detail_task = surf.get_wallet_detail(normalized, chain)
    history_task = surf.get_wallet_history(normalized, chain, history_limit)
    transfers_task = surf.get_wallet_transfers(normalized, chain, transfer_limit)
    net_worth_task = surf.get_wallet_net_worth(normalized, time_range)

    labels, detail, history, transfers, net_worth = await asyncio.gather(
        labels_task,
        detail_task,
        history_task,
        transfers_task,
        net_worth_task,
        return_exceptions=True,
    )

    entity = labels[0] if isinstance(labels, list) and labels else {
        "address": normalized,
        "blockchain": chain,
        "label": None,
        "entity_name": None,
        "address_type": "unknown",
        "is_whale": False,
        "score": None,
        "source": "surf:wallet-labels",
        "metadata": {},
    }
    detail_data = detail if isinstance(detail, dict) else {}
    history_items = history if isinstance(history, list) else []
    transfer_items = transfers if isinstance(transfers, list) else []
    worth_items = net_worth if isinstance(net_worth, list) else []

    latest_worth = worth_items[-1] if worth_items else None
    profile_summary = {
        "history_count": len(history_items),
        "transfer_count": len(transfer_items),
        "net_worth_points": len(worth_items),
        "latest_net_worth": latest_worth,
    }

    return {
        "entity": entity,
        "wallet_detail": detail_data,
        "history": history_items,
        "transfers": transfer_items,
        "net_worth": worth_items,
        "summary": profile_summary,
    }


async def _list_manual_monitored_addresses(
    *,
    chain: str | None = None,
    entity_type: str | None = None,
    is_whale: bool | None = None,
    q: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    if not db_available():
        return []

    async with async_session() as session:
        conditions = [MonitoredAddress.is_active == 1]
        if chain:
            conditions.append(MonitoredAddress.blockchain == chain.lower())
        if entity_type:
            conditions.append(MonitoredAddress.address_type == entity_type)
        if is_whale is not None:
            conditions.append(MonitoredAddress.is_whale == (1 if is_whale else 0))
        if q:
            pattern = f"%{q.strip()}%"
            conditions.append(
                or_(
                    MonitoredAddress.address.ilike(pattern),
                    MonitoredAddress.label.ilike(pattern),
                    MonitoredAddress.entity_name.ilike(pattern),
                )
            )

        stmt = (
            select(MonitoredAddress)
            .where(and_(*conditions))
            .order_by(MonitoredAddress.address_type.asc(), MonitoredAddress.created_at.desc())
            .limit(min(max(limit, 1), 200))
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [_serialize_monitored(row) for row in rows]


async def list_monitored_addresses(
    *,
    chain: str | None = None,
    entity_type: str | None = None,
    is_whale: bool | None = None,
    q: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    capped_limit = min(max(limit, 1), 200)
    legacy_items = await fetch_legacy_catalog(
        q=q,
        chain=chain,
        entity_type=entity_type,
        limit=capped_limit,
    )
    manual_items = await _list_manual_monitored_addresses(
        chain=chain,
        entity_type=entity_type,
        is_whale=is_whale,
        q=q,
        limit=capped_limit,
    )
    items = _sort_entities(_dedupe_entities([*legacy_items, *manual_items]))
    if is_whale is not None:
        items = [item for item in items if bool(item.get("is_whale")) is is_whale]
    return items[:capped_limit]


async def bulk_upsert_monitored_addresses(items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    picked = []
    for item in items:
        if not isinstance(item, dict):
            continue
        address = normalize_address(item.get("address"))
        if not address:
            continue
        picked.append({
            "address": address,
            "blockchain": _extract_chain(item, fallback="ethereum"),
            "label": _first_non_empty(item.get("label"), item.get("entity_name")),
            "entity_name": _first_non_empty(item.get("entity_name"), item.get("label")),
            "address_type": infer_address_type(item),
            "is_whale": 1 if infer_is_whale(item, address_type=infer_address_type(item)) else 0,
            "alert_threshold": _safe_float(item.get("alert_threshold")),
            "source": _first_non_empty(item.get("source"), "manual"),
            "metadata_json": item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
        })

    if not picked:
        return {"count": 0, "created": 0, "updated": 0, "items": []}
    if not db_available():
        return {"count": len(picked), "created": 0, "updated": 0, "items": picked, "warning": "Database not available"}

    created = 0
    updated = 0
    async with async_session() as session:
        for item in picked:
            stmt = select(MonitoredAddress).where(
                MonitoredAddress.address == item["address"],
                MonitoredAddress.blockchain == item["blockchain"],
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing:
                existing.label = item["label"]
                existing.entity_name = item["entity_name"]
                existing.address_type = item["address_type"]
                existing.is_whale = item["is_whale"]
                existing.alert_threshold = item["alert_threshold"]
                existing.source = item["source"]
                existing.is_active = 1
                existing.metadata_json = item["metadata_json"]
                updated += 1
            else:
                session.add(MonitoredAddress(**item))
                created += 1
        await session.commit()

    return {"count": len(picked), "created": created, "updated": updated, "items": picked}


async def sync_monitored_address_sources(
    *,
    include_legacy: bool = True,
    include_default_seeds: bool = True,
    legacy_entity_type: str | None = None,
    legacy_limit: int = 1000,
) -> dict[str, Any]:
    source_items: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {
        "legacy": 0,
        "default_seeds": 0,
    }
    warnings: list[str] = []

    if include_legacy:
        try:
            legacy_items = await fetch_registry_watch_addresses(
                entity_type=legacy_entity_type,
                limit=legacy_limit,
            )
            source_counts["legacy"] = len(legacy_items)
            source_items.extend(legacy_items)
        except Exception:
            warnings.append("Failed to load legacy registry watch addresses")

    if include_default_seeds:
        default_seed_items = get_default_monitored_address_seeds()
        source_counts["default_seeds"] = len(default_seed_items)
        source_items.extend(default_seed_items)

    result = await bulk_upsert_monitored_addresses(source_items)
    result["source_counts"] = source_counts
    result["include_legacy"] = include_legacy
    result["include_default_seeds"] = include_default_seeds
    result["legacy_entity_type"] = legacy_entity_type
    result["legacy_limit"] = legacy_limit
    result["warnings"] = warnings
    return result


async def ensure_default_whale_watch_addresses() -> dict[str, Any]:
    current = await _list_manual_monitored_addresses(is_whale=True, limit=5)
    if current:
        return {
            "seeded": False,
            "watched_address_count": len(current),
            "reason": "whale_watchers_already_present",
        }

    sync_result = await sync_monitored_address_sources(
        include_legacy=False,
        include_default_seeds=True,
        legacy_limit=0,
    )
    refreshed = await _list_manual_monitored_addresses(is_whale=True, limit=10)
    return {
        "seeded": True,
        "watched_address_count": len(refreshed),
        "created": sync_result.get("created", 0),
        "updated": sync_result.get("updated", 0),
        "count": sync_result.get("count", 0),
        "warnings": sync_result.get("warnings", []),
    }


async def _get_manual_monitored_overview(*, chain: str | None = None) -> dict[str, Any]:
    if not db_available():
        return {
            "tracked_count": 0,
            "active_count": 0,
            "exchange_count": 0,
            "institution_count": 0,
            "whale_count": 0,
            "type_breakdown": {},
            "db_available": False,
        }

    async with async_session() as session:
        conditions = [MonitoredAddress.is_active == 1]
        if chain:
            conditions.append(MonitoredAddress.blockchain == chain.lower())

        total_stmt = select(func.count()).select_from(MonitoredAddress).where(*conditions)
        tracked_count = int((await session.execute(total_stmt)).scalar() or 0)

        typed_stmt = (
            select(MonitoredAddress.address_type, func.count())
            .where(*conditions)
            .group_by(MonitoredAddress.address_type)
        )
        typed_rows = (await session.execute(typed_stmt)).all()
        breakdown = {str(address_type or "unknown"): int(count) for address_type, count in typed_rows}

        whale_stmt = select(func.count()).select_from(MonitoredAddress).where(*conditions, MonitoredAddress.is_whale == 1)
        whale_count = int((await session.execute(whale_stmt)).scalar() or 0)

    return {
        "tracked_count": tracked_count,
        "active_count": tracked_count,
        "exchange_count": breakdown.get("exchange", 0),
        "institution_count": breakdown.get("institution", 0),
        "whale_count": whale_count,
        "type_breakdown": breakdown,
        "db_available": True,
    }


async def get_monitored_overview(*, chain: str | None = None) -> dict[str, Any]:
    legacy_overview = await fetch_legacy_overview(chain=chain)
    manual_overview = await _get_manual_monitored_overview(chain=chain)
    if legacy_overview:
        return {
            **legacy_overview,
            "manual_watch_count": manual_overview.get("tracked_count", 0),
            "manual_watch_breakdown": manual_overview.get("type_breakdown", {}),
        }
    return manual_overview


@cached(ttl=60, prefix="address_intel_dashboard")
async def build_address_intel_dashboard(
    *,
    q: str | None = None,
    chain: str = "ethereum",
    entity_type: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    query = str(q or "").strip()
    overview = await get_monitored_overview(chain=chain)
    tracked_items = await list_monitored_addresses(
        chain=chain,
        entity_type=entity_type,
        q=query if query and not _is_address(query) else None,
        limit=limit,
    )

    search_results: list[dict[str, Any]] = []
    profile: dict[str, Any] | None = None
    if query:
        if _is_address(query):
            profile = await get_address_profile(query, chain=chain)
            search_results = [profile.get("entity", {})] if isinstance(profile, dict) and not profile.get("error") else []
        else:
            search_results = await search_address_entities(query, chain=chain, entity_type=entity_type, limit=limit)

    featured: dict[str, list[dict[str, Any]]] = {"exchanges": [], "institutions": [], "whales": []}
    for item in tracked_items:
        item_type = item.get("address_type")
        if item_type == "exchange" and len(featured["exchanges"]) < 6:
            featured["exchanges"].append(item)
        elif item_type == "institution" and len(featured["institutions"]) < 6:
            featured["institutions"].append(item)
        elif item.get("is_whale") and len(featured["whales"]) < 6:
            featured["whales"].append(item)

    return {
        "query": query or None,
        "chain": chain,
        "entity_type": entity_type,
        "overview": overview,
        "tracked_items": tracked_items,
        "search_results": search_results,
        "profile": profile,
        "featured": featured,
    }
