"""Address intelligence API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query

from app.address_intel.service import (
    build_address_intel_dashboard,
    bulk_upsert_monitored_addresses,
    classify_addresses,
    get_address_profile,
    list_monitored_addresses,
    search_address_entities,
    sync_monitored_address_sources,
)

router = APIRouter(prefix="/address-intel", tags=["address-intel"])


@router.get("/dashboard")
async def address_intel_dashboard(
    q: str | None = Query(None, description="Entity keyword or wallet address"),
    chain: str = Query("ethereum", description="Chain name"),
    entity_type: str | None = Query(None, description="exchange / institution / whale"),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    return await build_address_intel_dashboard(
        q=q,
        chain=chain,
        entity_type=entity_type,
        limit=limit,
    )


@router.get("/search")
async def address_intel_search(
    q: str = Query(..., description="Entity keyword or wallet address"),
    chain: str = Query("ethereum"),
    entity_type: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    items = await search_address_entities(q, chain=chain, entity_type=entity_type, limit=limit)
    return {
        "items": items,
        "count": len(items),
        "query": q,
        "chain": chain,
        "entity_type": entity_type,
    }


@router.get("/profile/{address}")
async def address_intel_profile(
    address: str,
    chain: str = Query("ethereum"),
    history_limit: int = Query(10, ge=1, le=50),
    transfer_limit: int = Query(10, ge=1, le=50),
    time_range: str = Query("30d"),
) -> dict[str, Any]:
    return await get_address_profile(
        address,
        chain=chain,
        history_limit=history_limit,
        transfer_limit=transfer_limit,
        time_range=time_range,
    )


@router.post("/classify")
async def address_intel_classify(
    addresses: list[str] = Body(..., embed=True),
    chain: str = Body("ethereum", embed=True),
    persist: bool = Body(False, embed=True),
) -> dict[str, Any]:
    items = await classify_addresses(addresses, chain=chain, persist=persist)
    return {
        "items": items,
        "count": len(items),
        "chain": chain,
        "persisted": persist,
    }


@router.get("/entities")
async def address_intel_entities(
    chain: str | None = Query(None),
    entity_type: str | None = Query(None),
    is_whale: bool | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    items = await list_monitored_addresses(
        chain=chain,
        entity_type=entity_type,
        is_whale=is_whale,
        q=q,
        limit=limit,
    )
    return {
        "items": items,
        "count": len(items),
        "chain": chain,
        "entity_type": entity_type,
        "is_whale": is_whale,
    }


@router.post("/entities/bulk-upsert")
async def address_intel_bulk_upsert(
    items: list[dict[str, Any]] = Body(..., embed=True),
) -> dict[str, Any]:
    return await bulk_upsert_monitored_addresses(items)


@router.post("/sync/sources")
async def address_intel_sync_sources(
    include_legacy: bool = Query(True),
    include_packaged_snapshot: bool = Query(True),
    include_default_seeds: bool = Query(True),
    legacy_entity_type: str | None = Query(None),
    legacy_limit: int = Query(1000, ge=0, le=5000),
) -> dict[str, Any]:
    return await sync_monitored_address_sources(
        include_legacy=include_legacy,
        include_packaged_snapshot=include_packaged_snapshot,
        include_default_seeds=include_default_seeds,
        legacy_entity_type=legacy_entity_type,
        legacy_limit=legacy_limit,
    )
