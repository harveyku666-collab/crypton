"""Standalone square APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.common.database import db_available
from app.common.models import SquareKOLProfile
from app.config import settings
from app.square.service import (
    SQUARE_ITEM_TYPES,
    SQUARE_PLATFORMS,
    collect_square_items,
    fetch_square_feed,
    filter_square_items,
    list_square_collection_states,
    generate_hot_coin_snapshot,
    list_kol_profiles,
    list_hot_coin_snapshots,
    load_hot_coin_board,
    normalize_platforms,
    query_square_history,
    serialize_live_square_item,
    upsert_kol_profiles,
)

router = APIRouter(prefix="/square", tags=["square"])


class SquareKOLProfileInput(BaseModel):
    platform: str
    name: str
    handle: str | None = None
    author_id: str | None = None
    aliases: list[str] = Field(default_factory=list)
    tier: str | None = None
    score: float | None = None
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


def _serialize_kol_profile(item: SquareKOLProfile) -> dict[str, Any]:
    stored_at = getattr(item, "created_at", None)
    return {
        "id": item.id,
        "platform": item.platform,
        "name": item.name,
        "handle": item.handle,
        "author_id": item.author_id,
        "aliases": item.aliases_json or [],
        "tier": item.tier,
        "score": item.score,
        "is_active": bool(item.is_active),
        "metadata": item.metadata_json or {},
        "stored_at": str(stored_at) if stored_at else None,
    }


@router.get("/live")
async def get_square_live(
    platforms: str = Query("binance,okx", description="Comma-separated platforms"),
    language: str = Query(settings.square_default_language, description="Preferred language"),
    item_type: str | None = Query(None, description="post, topic, article"),
    q: str | None = Query(None, description="Keyword search over title/content/author"),
    kol_only: bool = Query(False, description="Only return matched KOL authors"),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    selected_platforms = normalize_platforms([part.strip() for part in platforms.split(",") if part.strip()])
    payload = await fetch_square_feed(
        platforms=selected_platforms,
        limit=limit,
        language=language,
    )
    filtered = filter_square_items(
        payload.get("items", []),
        item_type=item_type,
        language=language,
        q=q,
        kol_only=kol_only,
    )
    return {
        "items": [serialize_live_square_item(item, index) for index, item in enumerate(filtered[:limit])],
        "count": min(len(filtered), limit),
        "platforms": selected_platforms,
        "source_mode": "live",
        "source_modes": payload.get("source_modes", {}),
        "errors": payload.get("errors", []),
        "warnings": payload.get("warnings", []),
        "filters": {
            "platforms": list(SQUARE_PLATFORMS),
            "item_types": list(SQUARE_ITEM_TYPES),
        },
    }


@router.get("/history")
async def get_square_history(
    platform: str | None = Query(None, description="binance or okx"),
    item_type: str | None = Query(None, description="post, topic, article"),
    language: str | None = Query(None, description="Language filter, e.g. en or zh-CN"),
    q: str | None = Query(None, description="Keyword search over title/content/author"),
    kol_only: bool = Query(False, description="Only return matched KOL authors"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
) -> dict[str, Any]:
    payload = await query_square_history(
        platform=platform,
        item_type=item_type,
        language=language,
        q=q,
        kol_only=kol_only,
        page=page,
        page_size=page_size,
    )
    payload["filters"] = {
        "platforms": list(SQUARE_PLATFORMS),
        "item_types": list(SQUARE_ITEM_TYPES),
    }
    return payload


@router.get("/hot-coins")
async def get_hot_coins(
    platforms: str = Query("binance,okx", description="Comma-separated platforms"),
    hours: int = Query(settings.square_hot_token_window_hours, ge=1, le=168),
    language: str = Query(settings.square_default_language),
    kol_only: bool = Query(False, description="Only count KOL matched authors"),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    selected_platforms = normalize_platforms([part.strip() for part in platforms.split(",") if part.strip()])
    payload = await load_hot_coin_board(
        platforms=selected_platforms,
        hours=hours,
        kol_only=kol_only,
        limit=limit,
        language=language,
    )
    payload["platforms"] = selected_platforms
    return payload


@router.get("/collect/status")
async def get_square_collect_status(
    platforms: str = Query("binance,okx", description="Comma-separated platforms"),
    language: str | None = Query(None, description="Optional language scope"),
) -> dict[str, Any]:
    if not db_available():
        raise HTTPException(status_code=503, detail="Database not available")
    selected_platforms = normalize_platforms([part.strip() for part in platforms.split(",") if part.strip()])
    items = await list_square_collection_states(platforms=selected_platforms, language=language)
    return {
        "items": items,
        "count": len(items),
        "platforms": selected_platforms,
    }


@router.post("/collect/run")
async def run_square_collect(
    platforms: str = Query("binance,okx", description="Comma-separated platforms"),
    language: str = Query(settings.square_default_language),
    page_size: int = Query(settings.square_collect_page_size, ge=1, le=50),
    backfill_pages: int = Query(settings.square_collect_backfill_pages, ge=0, le=10),
) -> dict[str, Any]:
    if not db_available():
        raise HTTPException(status_code=503, detail="Database not available")
    selected_platforms = normalize_platforms([part.strip() for part in platforms.split(",") if part.strip()])
    return await collect_square_items(
        platforms=selected_platforms,
        page_size=page_size,
        backfill_pages=backfill_pages,
        language=language,
    )


@router.get("/kols")
async def get_kols(platform: str | None = Query(None, description="binance or okx")) -> dict[str, Any]:
    profiles = await list_kol_profiles(platform)
    return {
        "items": [_serialize_kol_profile(item) for item in profiles],
        "count": len(profiles),
    }


@router.post("/kols/bulk-upsert")
async def bulk_upsert_kols(items: list[SquareKOLProfileInput]) -> dict[str, Any]:
    if not db_available():
        raise HTTPException(status_code=503, detail="Database not available")
    result = await upsert_kol_profiles([item.model_dump() for item in items])
    return result


@router.post("/hot-coins/snapshots/generate")
async def generate_hot_coin_snapshot_endpoint(
    platforms: str = Query("binance,okx", description="Comma-separated platforms"),
    hours: int = Query(settings.square_hot_token_window_hours, ge=1, le=168),
    kol_only: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
    snapshot_date: str | None = Query(None, description="Override snapshot date, e.g. 2026-04-20"),
) -> dict[str, Any]:
    if not db_available():
        raise HTTPException(status_code=503, detail="Database not available")
    selected_platforms = normalize_platforms([part.strip() for part in platforms.split(",") if part.strip()])
    return await generate_hot_coin_snapshot(
        platforms=selected_platforms,
        hours=hours,
        kol_only=kol_only,
        limit=limit,
        snapshot_date=snapshot_date,
    )


@router.get("/hot-coins/snapshots")
async def get_hot_coin_snapshots(
    platforms: str = Query("binance,okx", description="Comma-separated platforms"),
    snapshot_date: str | None = Query(None, description="Filter by snapshot date, e.g. 2026-04-20"),
    kol_only: bool | None = Query(None, description="Filter KOL-only or all-author snapshots"),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    if not db_available():
        raise HTTPException(status_code=503, detail="Database not available")
    selected_platforms = normalize_platforms([part.strip() for part in platforms.split(",") if part.strip()])
    payload = await list_hot_coin_snapshots(
        snapshot_date=snapshot_date,
        platforms=selected_platforms,
        kol_only=kol_only,
        limit=limit,
    )
    payload["platforms"] = selected_platforms
    return payload
