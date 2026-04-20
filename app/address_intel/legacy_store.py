"""Read-only legacy address intelligence data store.

This adapter lets BitInfo reuse the old project's entity/address/activity
tables without copying them into the current service database first.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import settings

logger = logging.getLogger("bitinfo.address_intel.legacy")

REGISTRY = "registry"
ACTIVITY = "activity"
_PROBE_FAIL_TTL_SECONDS = 60.0

_engines: dict[str, AsyncEngine | None] = {REGISTRY: None, ACTIVITY: None}
_resolved_urls: dict[str, str | None] = {REGISTRY: None, ACTIVITY: None}
_last_probe_at: dict[str, float] = {REGISTRY: 0.0, ACTIVITY: 0.0}
_probe_lock = asyncio.Lock()


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _candidate_urls(kind: str) -> list[str]:
    explicit = (
        settings.address_intel_registry_database_url
        if kind == REGISTRY
        else settings.address_intel_activity_database_url
    )
    urls = [item.strip() for item in str(explicit or "").split(",") if item.strip()]
    if kind == REGISTRY:
        urls.extend(
            [
                "postgresql+asyncpg:///trading?host=/tmp",
                "postgresql+asyncpg://test@/trading?host=/tmp",
            ]
        )
    else:
        urls.extend(
            [
                "postgresql+asyncpg:///trading_test?host=/tmp",
                "postgresql+asyncpg://test@/trading_test?host=/tmp",
            ]
        )
    return _dedupe(urls)


async def _resolve_engine(kind: str) -> AsyncEngine | None:
    engine = _engines.get(kind)
    if engine is not None:
        return engine

    now = time.monotonic()
    if _last_probe_at.get(kind, 0.0) and now - _last_probe_at[kind] < _PROBE_FAIL_TTL_SECONDS:
        return None

    async with _probe_lock:
        engine = _engines.get(kind)
        if engine is not None:
            return engine

        now = time.monotonic()
        if _last_probe_at.get(kind, 0.0) and now - _last_probe_at[kind] < _PROBE_FAIL_TTL_SECONDS:
            return None

        for url in _candidate_urls(kind):
            candidate = create_async_engine(
                url,
                echo=settings.debug,
                pool_pre_ping=True,
                pool_size=2,
                max_overflow=0,
                connect_args={"timeout": 2},
            )
            try:
                async with candidate.connect() as conn:
                    await conn.execute(text("select 1"))
                _engines[kind] = candidate
                _resolved_urls[kind] = url
                _last_probe_at[kind] = time.monotonic()
                logger.info("Address intel legacy %s DB connected via %s", kind, url)
                return candidate
            except Exception:
                await candidate.dispose()

        _resolved_urls[kind] = None
        _last_probe_at[kind] = time.monotonic()
        logger.info("Address intel legacy %s DB unavailable", kind)
        return None


async def close_legacy_engines() -> None:
    for kind, engine in list(_engines.items()):
        if engine is not None:
            await engine.dispose()
        _engines[kind] = None
        _resolved_urls[kind] = None
        _last_probe_at[kind] = 0.0


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _row_dict(row: Any) -> dict[str, Any]:
    return {key: _json_safe(value) for key, value in dict(row).items()}


async def _fetch_all(kind: str, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    engine = await _resolve_engine(kind)
    if engine is None:
        return []
    async with engine.connect() as conn:
        result = await conn.execute(text(sql), params or {})
        return [_row_dict(row) for row in result.mappings().all()]


async def _fetch_one(kind: str, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    rows = await _fetch_all(kind, sql, params=params)
    return rows[0] if rows else None


def _normalize_entity_type(value: Any) -> str:
    return str(value or "unknown").strip().lower() or "unknown"


def _normalize_registry_item(row: dict[str, Any], *, chain: str | None = None) -> dict[str, Any]:
    entity_type = _normalize_entity_type(row.get("entity_type"))
    score = row.get("confidence_score")
    return {
        "id": f"legacy-registry-{row.get('entity_id')}",
        "address": row.get("address"),
        "blockchain": row.get("chain_code") or chain or "multi",
        "label": row.get("address_label") or row.get("entity_name"),
        "entity_name": row.get("entity_name"),
        "address_type": entity_type,
        "is_whale": entity_type == "whale",
        "score": float(score) if score is not None else None,
        "source": row.get("entity_source") or "legacy-registry",
        "metadata": {
            "legacy_source": "trading.entity",
            "entity_id": row.get("entity_id"),
            "category": row.get("category"),
            "description": row.get("description"),
            "address_role": row.get("address_role"),
            "chain_name": row.get("chain_name"),
            "confidence_score": row.get("confidence_score"),
            "entity_updated_at": row.get("entity_updated_at"),
            "address_updated_at": row.get("address_updated_at"),
            "address_source": row.get("address_source"),
        },
    }


def _normalize_activity_item(row: dict[str, Any], *, chain: str | None = None) -> dict[str, Any]:
    entity_type = _normalize_entity_type(row.get("entity_type"))
    score = row.get("confidence_score")
    return {
        "id": f"legacy-activity-{row.get('entity_id')}",
        "address": None,
        "blockchain": chain or "multi",
        "label": row.get("entity_name"),
        "entity_name": row.get("entity_name"),
        "address_type": entity_type,
        "is_whale": entity_type == "whale",
        "score": float(score) if score is not None else None,
        "source": row.get("entity_source") or "legacy-activity",
        "metadata": {
            "legacy_source": "trading_test.entity",
            "entity_id": row.get("entity_id"),
            "category": row.get("category"),
            "description": row.get("description"),
            "latest_report_date": row.get("latest_report_date"),
            "latest_event_count": row.get("latest_event_count"),
            "latest_daily_summary": row.get("latest_daily_summary"),
            "latest_week_start": row.get("latest_week_start"),
            "latest_week_end": row.get("latest_week_end"),
            "latest_weekly_summary": row.get("latest_weekly_summary"),
            "entity_updated_at": row.get("entity_updated_at"),
        },
    }


def _normalized_key(item: dict[str, Any]) -> str:
    return str(item.get("address") or item.get("entity_name") or item.get("label") or "").strip().lower()


def merge_entities(*groups: list[dict[str, Any]], limit: int = 50) -> list[dict[str, Any]]:
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for group in groups:
        for item in group:
            key = _normalized_key(item)
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= limit:
                return merged
    return merged


def _sort_entities(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    type_rank = {"exchange": 0, "institution": 1, "whale": 2}

    def _sort_key(item: dict[str, Any]) -> tuple[int, int, float, str]:
        return (
            type_rank.get(str(item.get("address_type") or "unknown"), 9),
            0 if item.get("address") else 1,
            -float(item.get("score") or 0),
            str(item.get("entity_name") or item.get("label") or "").lower(),
        )

    return sorted(items, key=_sort_key)


def _to_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except Exception:
            return None
    return None


def build_freshness_status(
    *,
    last_daily_report_date: Any = None,
    last_event_at: Any = None,
    last_weekly_report_date: Any = None,
) -> dict[str, Any]:
    today = datetime.now(timezone.utc).date()
    daily = _to_date(last_daily_report_date)
    event_day = _to_date(last_event_at)
    weekly = _to_date(last_weekly_report_date)

    warnings: list[str] = []
    status = "unavailable"

    latest_known = daily or event_day or weekly
    if latest_known is None:
        warnings.append("Legacy activity summaries are not available yet.")
    elif latest_known > today + timedelta(days=1):
        status = "future_sample_data"
        warnings.append(
            f"Legacy activity data is dated {latest_known.isoformat()}, later than today {today.isoformat()}."
        )
    elif latest_known < today - timedelta(days=3):
        status = "stale"
        warnings.append(
            f"Legacy activity data is stale. Latest available date is {latest_known.isoformat()}."
        )
    else:
        status = "fresh"

    return {
        "status": status,
        "today": today.isoformat(),
        "last_daily_report_date": daily.isoformat() if daily else None,
        "last_event_at": str(last_event_at) if last_event_at else None,
        "last_weekly_report_date": weekly.isoformat() if weekly else None,
        "warnings": warnings,
    }


async def fetch_registry_entities(
    *,
    q: str | None = None,
    chain: str | None = None,
    entity_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    query = str(q or "").strip()
    chain_code = str(chain or "").strip().lower() or None
    normalized_type = str(entity_type or "").strip().lower() or None
    params: dict[str, Any] = {"limit": min(max(limit, 1), 200)}

    lateral_chain_filter = ""
    if chain_code:
        lateral_chain_filter = "and lower(c.chain_code) = :chain_code"
        params["chain_code"] = chain_code

    where_clauses = ["e.status = 'active'"]
    if normalized_type:
        where_clauses.append("lower(e.entity_type) = :entity_type")
        params["entity_type"] = normalized_type
    if query:
        where_clauses.append(
            """
            (
              e.name ilike :pattern
              or coalesce(e.description, '') ilike :pattern
              or exists (
                select 1
                from entity_address sea
                where sea.entity_id = e.id
                  and (
                    sea.address ilike :pattern
                    or coalesce(sea.label, '') ilike :pattern
                  )
              )
            )
            """
        )
        params["pattern"] = f"%{query}%"
    if chain_code:
        where_clauses.append(
            """
            (
              addr.address is not null
              or not exists (select 1 from entity_address sea where sea.entity_id = e.id)
            )
            """
        )

    sql = f"""
    select
      e.id as entity_id,
      e.name as entity_name,
      lower(e.entity_type) as entity_type,
      e.category,
      e.description,
      e.source as entity_source,
      e.confidence_score,
      e.updated_at as entity_updated_at,
      addr.address,
      addr.address_role,
      addr.address_label,
      addr.address_source,
      addr.address_updated_at,
      addr.chain_code,
      addr.chain_name
    from entity e
    left join lateral (
      select
        ea.address,
        lower(ea.address_role) as address_role,
        ea.label as address_label,
        ea.source as address_source,
        ea.updated_at as address_updated_at,
        lower(c.chain_code) as chain_code,
        c.chain_name
      from entity_address ea
      join chain c on c.id = ea.chain_id
      where ea.entity_id = e.id
        and ea.status = 'active'
        {lateral_chain_filter}
      order by
        case lower(ea.address_role)
          when 'main' then 0
          when 'hot' then 1
          when 'cold' then 2
          else 9
        end,
        ea.updated_at desc,
        ea.id asc
      limit 1
      ) addr on true
    where {" and ".join(where_clauses)}
    order by
      case lower(e.entity_type)
        when 'exchange' then 0
        when 'institution' then 1
        when 'whale' then 2
        else 9
      end,
      e.confidence_score desc,
      e.updated_at desc,
      e.id asc
    limit :limit
    """
    rows = await _fetch_all(
        REGISTRY,
        sql,
        params,
    )
    return [_normalize_registry_item(row, chain=chain) for row in rows]


async def fetch_registry_watch_addresses(
    *,
    entity_type: str | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    normalized_type = str(entity_type or "").strip().lower() or None
    params: dict[str, Any] = {"limit": min(max(limit, 1), 5000)}
    where_clauses = [
        "e.status = 'active'",
        "ea.status = 'active'",
    ]
    if normalized_type:
        where_clauses.append("lower(e.entity_type) = :entity_type")
        params["entity_type"] = normalized_type

    sql = f"""
    select
      e.id as entity_id,
      e.name as entity_name,
      lower(e.entity_type) as entity_type,
      e.category,
      e.description,
      e.source as entity_source,
      e.confidence_score,
      e.updated_at as entity_updated_at,
      ea.address,
      lower(ea.address_role) as address_role,
      ea.label as address_label,
      ea.source as address_source,
      ea.updated_at as address_updated_at,
      lower(c.chain_code) as chain_code,
      c.chain_name
    from entity e
    join entity_address ea on ea.entity_id = e.id
    join chain c on c.id = ea.chain_id
    where {" and ".join(where_clauses)}
    order by
      case lower(e.entity_type)
        when 'exchange' then 0
        when 'institution' then 1
        when 'whale' then 2
        else 9
      end,
      e.name asc,
      c.chain_code asc,
      ea.id asc
    limit :limit
    """
    rows = await _fetch_all(REGISTRY, sql, params)
    return [_normalize_registry_item(row, chain=row.get("chain_code")) for row in rows]


async def fetch_activity_entities(
    *,
    q: str | None = None,
    entity_type: str | None = None,
    limit: int = 50,
    chain: str | None = None,
) -> list[dict[str, Any]]:
    query = str(q or "").strip()
    normalized_type = str(entity_type or "").strip().lower() or None
    params: dict[str, Any] = {"limit": min(max(limit, 1), 200)}
    where_clauses = ["e.status = 'active'"]
    if normalized_type:
        where_clauses.append("lower(e.entity_type) = :entity_type")
        params["entity_type"] = normalized_type
    if query:
        where_clauses.append(
            """
            (
              e.name ilike :pattern
              or coalesce(d.summary_text, '') ilike :pattern
              or coalesce(w.summary_text, '') ilike :pattern
            )
            """
        )
        params["pattern"] = f"%{query}%"

    sql = f"""
    select
      e.id as entity_id,
      e.name as entity_name,
      lower(e.entity_type) as entity_type,
      e.category,
      e.description,
      e.source as entity_source,
      e.confidence_score,
      e.updated_at as entity_updated_at,
      d.report_date as latest_report_date,
      d.event_count as latest_event_count,
      d.summary_text as latest_daily_summary,
      w.week_start as latest_week_start,
      w.week_end as latest_week_end,
      w.summary_text as latest_weekly_summary
    from entity e
    left join lateral (
      select report_date, event_count, summary_text
      from daily_entity_focus_summary d
      where d.entity_id = e.id
      order by d.report_date desc, d.id desc
      limit 1
    ) d on true
    left join lateral (
      select week_start, week_end, summary_text
      from weekly_entity_movement_summary w
      where w.entity_id = e.id
      order by w.week_start desc, w.id desc
      limit 1
    ) w on true
    where {" and ".join(where_clauses)}
    order by coalesce(d.report_date, date '1900-01-01') desc, e.updated_at desc, e.id asc
    limit :limit
    """
    rows = await _fetch_all(
        ACTIVITY,
        sql,
        params,
    )
    return [_normalize_activity_item(row, chain=chain) for row in rows]


async def fetch_legacy_catalog(
    *,
    q: str | None = None,
    chain: str | None = None,
    entity_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    registry_items = await fetch_registry_entities(
        q=q,
        chain=chain,
        entity_type=entity_type,
        limit=max(limit, 50),
    )
    activity_items: list[dict[str, Any]] = []
    if entity_type in {None, "", "whale"}:
        activity_items = await fetch_activity_entities(
            q=q,
            entity_type=entity_type or None,
            limit=max(limit, 50),
            chain=chain,
        )
    merged = merge_entities(registry_items, activity_items, limit=max(limit, 50))
    return _sort_entities(merged)[:limit]


async def fetch_registry_entity_by_address(address: str) -> dict[str, Any] | None:
    sql = """
    select
      e.id as entity_id,
      e.name as entity_name,
      lower(e.entity_type) as entity_type,
      e.category,
      e.description,
      e.source as entity_source,
      e.confidence_score,
      e.updated_at as entity_updated_at,
      ea.address,
      lower(ea.address_role) as address_role,
      ea.label as address_label,
      ea.source as address_source,
      ea.updated_at as address_updated_at,
      lower(c.chain_code) as chain_code,
      c.chain_name
    from entity_address ea
    join entity e on e.id = ea.entity_id
    join chain c on c.id = ea.chain_id
    where lower(ea.address) = lower(:address)
      and ea.status = 'active'
      and e.status = 'active'
    order by
      case lower(ea.address_role)
        when 'main' then 0
        when 'hot' then 1
        when 'cold' then 2
        else 9
      end,
      ea.updated_at desc,
      ea.id asc
    limit 1
    """
    row = await _fetch_one(REGISTRY, sql, {"address": address})
    return _normalize_registry_item(row) if row else None


async def fetch_activity_profile_by_name(
    entity_name: str,
    *,
    history_limit: int = 10,
    transfer_limit: int = 10,
) -> dict[str, Any] | None:
    if not entity_name:
        return None

    entity_sql = """
    select id, name, lower(entity_type) as entity_type, category, description, source, confidence_score, updated_at
    from entity
    where lower(name) = lower(:entity_name)
      and status = 'active'
    order by updated_at desc, id desc
    limit 1
    """
    entity = await _fetch_one(ACTIVITY, entity_sql, {"entity_name": entity_name})
    if not entity:
        return None

    entity_id = entity["id"]
    events_sql = """
    select
      ime.id,
      ime.event_type,
      ime.severity,
      ime.snapshot_time_prev,
      ime.snapshot_time_new,
      ime.prev_value_usd,
      ime.new_value_usd,
      ime.delta_value_usd,
      ime.pool_reason,
      ime.watch_source,
      ime.event_summary,
      a.asset_symbol,
      a.asset_name,
      c.chain_code,
      c.chain_name
    from institutional_movement_event ime
    left join asset a on a.id = ime.asset_id
    left join chain c on c.id = ime.chain_id
    where ime.entity_id = :entity_id
    order by ime.snapshot_time_new desc, ime.id desc
    limit :limit
    """
    daily_sql = """
    select report_date, event_count, top_event_types, severity_mix, summary_text, updated_at
    from daily_entity_focus_summary
    where entity_id = :entity_id
    order by report_date desc, id desc
    limit :limit
    """
    weekly_sql = """
    select week_start, week_end, event_count, top_event_types, severity_mix, summary_text, updated_at
    from weekly_entity_movement_summary
    where entity_id = :entity_id
    order by week_start desc, id desc
    limit :limit
    """
    events = await _fetch_all(ACTIVITY, events_sql, {"entity_id": entity_id, "limit": min(max(transfer_limit, 1), 50)})
    daily = await _fetch_all(ACTIVITY, daily_sql, {"entity_id": entity_id, "limit": min(max(history_limit, 1), 50)})
    weekly = await _fetch_all(ACTIVITY, weekly_sql, {"entity_id": entity_id, "limit": min(max(history_limit, 1), 20)})

    latest_event = events[0] if events else None
    history_items = [
        {
            "type": "daily_focus",
            "action": "daily_focus",
            "symbol": entity_name,
            "report_date": row.get("report_date"),
            "event_count": row.get("event_count"),
            "summary_text": row.get("summary_text"),
            "severity_mix": row.get("severity_mix"),
        }
        for row in daily
    ]
    history_items.extend(
        {
            "type": "weekly_summary",
            "action": "weekly_summary",
            "symbol": entity_name,
            "report_date": row.get("week_start"),
            "event_count": row.get("event_count"),
            "summary_text": row.get("summary_text"),
            "severity_mix": row.get("severity_mix"),
        }
        for row in weekly
    )
    transfer_items = [
        {
            "type": row.get("event_type"),
            "token": row.get("asset_symbol") or row.get("asset_name"),
            "symbol": row.get("asset_symbol"),
            "counterparty": row.get("event_type"),
            "to": row.get("chain_code") or row.get("chain_name"),
            "usd_value": row.get("delta_value_usd"),
            "value_usd": row.get("new_value_usd"),
            "severity": row.get("severity"),
            "summary": row.get("event_summary"),
            "time": row.get("snapshot_time_new"),
        }
        for row in events
    ]

    freshness = build_freshness_status(
        last_daily_report_date=daily[0]["report_date"] if daily else None,
        last_event_at=latest_event["snapshot_time_new"] if latest_event else None,
        last_weekly_report_date=weekly[0]["week_start"] if weekly else None,
    )

    return {
        "entity": entity,
        "movement_events": events,
        "daily_focus": daily,
        "weekly_summaries": weekly,
        "history": history_items[:history_limit],
        "transfers": transfer_items[:transfer_limit],
        "summary": {
            "history_count": len(history_items),
            "transfer_count": len(transfer_items),
            "net_worth_points": 1 if latest_event and latest_event.get("new_value_usd") is not None else 0,
            "latest_net_worth": {
                "usd_value": latest_event.get("new_value_usd"),
                "time": latest_event.get("snapshot_time_new"),
            }
            if latest_event and latest_event.get("new_value_usd") is not None
            else None,
            "last_event_at": latest_event.get("snapshot_time_new") if latest_event else None,
            "freshness": freshness,
        },
    }


async def fetch_legacy_overview(chain: str | None = None) -> dict[str, Any] | None:
    registry_items = await fetch_registry_entities(chain=chain, limit=500)
    activity_items = await fetch_activity_entities(entity_type="whale", limit=500, chain=chain)
    merged_items = merge_entities(registry_items, activity_items, limit=1000)
    if not merged_items and _resolved_urls.get(REGISTRY) is None and _resolved_urls.get(ACTIVITY) is None:
        return None

    type_breakdown: dict[str, int] = {}
    for item in merged_items:
        item_type = _normalize_entity_type(item.get("address_type"))
        type_breakdown[item_type] = type_breakdown.get(item_type, 0) + 1

    registry_state = await _fetch_one(
        REGISTRY,
        """
        select
          count(*) as entity_count,
          count(*) filter (where status = 'active') as active_entity_count,
          max(updated_at) as last_registry_update
        from entity
        """,
    ) or {}
    activity_state = await _fetch_one(
        ACTIVITY,
        """
        select
          max(snapshot_time_new) as last_event_at,
          max(created_at) as last_ingest_at,
          count(*) as movement_event_count
        from institutional_movement_event
        """,
    ) or {}
    daily_state = await _fetch_one(
        ACTIVITY,
        """
        select
          max(report_date) as last_daily_report_date,
          count(*) as daily_summary_count
        from daily_entity_focus_summary
        """,
    ) or {}
    weekly_state = await _fetch_one(
        ACTIVITY,
        """
        select
          max(week_start) as last_weekly_report_date,
          count(*) as weekly_summary_count
        from weekly_entity_movement_summary
        """,
    ) or {}
    address_state = await _fetch_one(
        REGISTRY,
        """
        select count(*) as tracked_address_count
        from entity_address ea
        where ea.status = 'active'
        """,
    ) or {}

    freshness = build_freshness_status(
        last_daily_report_date=daily_state.get("last_daily_report_date"),
        last_event_at=activity_state.get("last_event_at"),
        last_weekly_report_date=weekly_state.get("last_weekly_report_date"),
    )

    return {
        "tracked_count": len(merged_items),
        "active_count": int(registry_state.get("active_entity_count") or len(merged_items)),
        "tracked_address_count": int(address_state.get("tracked_address_count") or 0),
        "exchange_count": type_breakdown.get("exchange", 0),
        "institution_count": type_breakdown.get("institution", 0),
        "whale_count": type_breakdown.get("whale", 0),
        "type_breakdown": type_breakdown,
        "db_available": True,
        "source_mode": "legacy",
        "registry_database_url": _resolved_urls.get(REGISTRY),
        "activity_database_url": _resolved_urls.get(ACTIVITY),
        "last_registry_update": registry_state.get("last_registry_update"),
        "last_event_at": activity_state.get("last_event_at"),
        "last_daily_report_date": daily_state.get("last_daily_report_date"),
        "last_weekly_report_date": weekly_state.get("last_weekly_report_date"),
        "movement_event_count": int(activity_state.get("movement_event_count") or 0),
        "daily_summary_count": int(daily_state.get("daily_summary_count") or 0),
        "weekly_summary_count": int(weekly_state.get("weekly_summary_count") or 0),
        "freshness": freshness,
        "warnings": freshness.get("warnings") or [],
    }


async def legacy_source_available() -> bool:
    registry_engine = await _resolve_engine(REGISTRY)
    activity_engine = await _resolve_engine(ACTIVITY)
    return registry_engine is not None or activity_engine is not None
