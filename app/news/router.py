"""News API routes with multi-language support."""

from __future__ import annotations

import math
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import desc, func, or_, select

from app.news import okx_orbit
from app.news.fetcher import (
    NEWS_CATEGORIES,
    SUPPORTED_LANGUAGES,
    fetch_all_news,
    fetch_desk3_news,
    fetch_multilang_news,
)

router = APIRouter(prefix="/news", tags=["news"])

NEWS_SENTIMENTS = ("bullish", "bearish", "neutral")
NEWS_IMPORTANCE = ("important", "normal")


def _normalize_filter(value: str | None) -> str | None:
    if value is None or not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized or None


def _serialize_news_item(item: Any) -> dict[str, Any]:
    content = getattr(item, "content", None)
    published_at = getattr(item, "published_at", None)
    stored_at = getattr(item, "created_at", None)
    return {
        "id": getattr(item, "id", None),
        "title": getattr(item, "title", ""),
        "content": content,
        "excerpt": (content or "")[:280],
        "source": getattr(item, "source", ""),
        "category": getattr(item, "category", ""),
        "language": getattr(item, "language", ""),
        "sentiment": getattr(item, "sentiment", "neutral"),
        "importance": getattr(item, "importance", "normal"),
        "published_at": published_at,
        "url": getattr(item, "url", None),
        "stored_at": str(stored_at) if stored_at else None,
    }


def _serialize_live_news_item(item: dict[str, Any], index: int) -> dict[str, Any]:
    content = item.get("description") or item.get("content") or ""
    published_at = item.get("published_at")
    return {
        "id": item.get("external_id") or f"live_{index}",
        "title": item.get("title", ""),
        "content": content,
        "excerpt": content[:280],
        "source": item.get("source", "desk3"),
        "category": item.get("category", ""),
        "language": item.get("language", ""),
        "sentiment": item.get("sentiment", "neutral"),
        "importance": item.get("importance", "normal"),
        "published_at": published_at,
        "url": item.get("url"),
        "stored_at": published_at,
    }


def _apply_live_filters(
    items: list[dict[str, Any]],
    *,
    q: str | None,
    sentiment: str | None,
    importance: str | None,
) -> list[dict[str, Any]]:
    keyword = (q or "").strip().lower()
    filtered = items
    if keyword:
        filtered = [
            item for item in filtered
            if keyword in f"{item.get('title', '')} {item.get('description', '')} {item.get('content', '')}".lower()
        ]
    if sentiment:
        filtered = [item for item in filtered if item.get("sentiment") == sentiment]
    if importance:
        filtered = [item for item in filtered if item.get("importance") == importance]
    return filtered


async def _fetch_live_news_page(
    *,
    language: str,
    category: str | None,
    q: str | None,
    sentiment: str | None,
    importance: str | None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    category_value = _normalize_filter(category)
    selected_categories = [category_value] if category_value in NEWS_CATEGORIES else list(NEWS_CATEGORIES.keys())

    if len(selected_categories) == 1:
        live_items = await fetch_desk3_news(
            category=selected_categories[0],
            count=page_size,
            language=language,
            page=page,
        )
        filtered = _apply_live_filters(
            live_items,
            q=q,
            sentiment=sentiment,
            importance=importance,
        )
        serialized = [_serialize_live_news_item(item, idx) for idx, item in enumerate(filtered)]
        return {
            "items": serialized,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": None,
                "total_pages": None,
                "has_prev": page > 1,
                "has_next": len(live_items) == page_size,
            },
            "db_available": False,
            "source_mode": "live",
            "filters": {
                "categories": list(NEWS_CATEGORIES.keys()),
                "sentiments": list(NEWS_SENTIMENTS),
                "importance": list(NEWS_IMPORTANCE),
            },
            "warning": "Database not available. Falling back to live Desk3 news.",
        }

    window_size = min(max(page * page_size, page_size), 60)
    results = await fetch_multilang_news(
        languages=[language],
        categories=selected_categories,
        count=window_size,
    )
    merged: list[dict[str, Any]] = []
    for selected_category in selected_categories:
        merged.extend(results.get(language, {}).get(selected_category, []))

    filtered = _apply_live_filters(
        merged,
        q=q,
        sentiment=sentiment,
        importance=importance,
    )
    filtered.sort(key=lambda item: str(item.get("published_at") or ""), reverse=True)

    start = (page - 1) * page_size
    end = start + page_size
    page_items = filtered[start:end]
    serialized = [_serialize_live_news_item(item, idx + start) for idx, item in enumerate(page_items)]
    return {
        "items": serialized,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": len(filtered),
            "total_pages": math.ceil(len(filtered) / page_size) if filtered else 0,
            "has_prev": page > 1,
            "has_next": end < len(filtered),
        },
        "db_available": False,
        "source_mode": "live",
        "filters": {
            "categories": list(NEWS_CATEGORIES.keys()),
            "sentiments": list(NEWS_SENTIMENTS),
            "importance": list(NEWS_IMPORTANCE),
        },
        "warning": "Database not available. Falling back to live Desk3 news.",
    }


@router.get("/")
async def get_all_news(language: str = Query("en", description="Language code")) -> dict:
    """Get all news categories in specified language (live from API)."""
    return await fetch_all_news(language)


@router.get("/languages")
async def list_languages() -> dict[str, str]:
    """List all supported news languages."""
    return SUPPORTED_LANGUAGES


@router.get("/multilang")
async def get_multilang_news(
    languages: str = Query("en,zh", description="Comma-separated language codes"),
    categories: str = Query("crypto,policy", description="Comma-separated categories"),
    count: int = Query(10, le=50),
) -> dict:
    """Get news in multiple languages simultaneously."""
    langs = [l.strip() for l in languages.split(",")]
    cats = [c.strip() for c in categories.split(",")]
    return await fetch_multilang_news(langs, cats, count)


@router.get("/history")
async def get_news_history(
    language: str = Query("en"),
    category: str | None = Query(None),
    sentiment: str | None = Query(None, description="Filter: bullish, bearish, neutral"),
    importance: str | None = Query(None, description="Filter: important, normal"),
    q: str | None = Query(None, description="Keyword search over title/content"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    limit: int | None = Query(None, ge=1, le=200),
) -> dict[str, Any]:
    """Get stored news from database (historical) with sentiment/importance."""
    from app.common.database import async_session, db_available
    from app.common.models import NewsItem

    category_value = _normalize_filter(category)
    sentiment_value = _normalize_filter(sentiment)
    importance_value = _normalize_filter(importance)
    keyword = q.strip() if isinstance(q, str) else ""
    effective_limit = limit if isinstance(limit, int) and limit > 0 else None
    effective_page_size = min(effective_limit or page_size, 50)

    if not db_available():
        return await _fetch_live_news_page(
            language=language,
            category=category_value,
            q=keyword,
            sentiment=sentiment_value,
            importance=importance_value,
            page=page,
            page_size=effective_page_size,
        )

    try:
        async with async_session() as session:
            conditions = [NewsItem.language == language]
            if category_value and category_value in NEWS_CATEGORIES:
                conditions.append(NewsItem.category == category_value)
            if sentiment_value in NEWS_SENTIMENTS:
                conditions.append(NewsItem.sentiment == sentiment_value)
            if importance_value in NEWS_IMPORTANCE:
                conditions.append(NewsItem.importance == importance_value)
            if keyword:
                pattern = f"%{keyword}%"
                conditions.append(
                    or_(
                        NewsItem.title.ilike(pattern),
                        NewsItem.content.ilike(pattern),
                        NewsItem.source.ilike(pattern),
                    )
                )

            total_stmt = select(func.count()).select_from(NewsItem).where(*conditions)
            total = int((await session.execute(total_stmt)).scalar() or 0)
            total_pages = math.ceil(total / effective_page_size) if total else 0
            current_page = min(page, total_pages) if total_pages else 1

            stmt = select(NewsItem).where(*conditions)
            stmt = stmt.order_by(desc(NewsItem.created_at)).offset((current_page - 1) * effective_page_size).limit(effective_page_size)
            result = await session.execute(stmt)
            items = result.scalars().all()

            return {
                "items": [_serialize_news_item(item) for item in items],
                "pagination": {
                    "page": current_page,
                    "page_size": effective_page_size,
                    "total": total,
                    "total_pages": total_pages,
                    "has_prev": current_page > 1,
                    "has_next": current_page < total_pages,
                },
                "db_available": True,
                "source_mode": "database",
                "filters": {
                    "categories": list(NEWS_CATEGORIES.keys()),
                    "sentiments": list(NEWS_SENTIMENTS),
                    "importance": list(NEWS_IMPORTANCE),
                },
            }
    except Exception:
        fallback = await _fetch_live_news_page(
            language=language,
            category=category_value,
            q=keyword,
            sentiment=sentiment_value,
            importance=importance_value,
            page=page,
            page_size=effective_page_size,
        )
        fallback["warning"] = "Database query failed. Falling back to live Desk3 news."
        return fallback


@router.get("/detail/{article_id}")
async def news_detail(article_id: str) -> dict[str, Any]:
    """Full article detail via Surf."""
    from app.market.sources.surf import get_news_detail
    result = await get_news_detail(article_id)
    return result or {"error": f"No article found for {article_id}"}


@router.get("/okx/latest")
async def okx_latest_news(
    coins: str | None = Query(None, description="Comma-separated symbols, e.g. BTC,ETH"),
    importance: str | None = Query(None, description="high or low"),
    platform: str | None = Query(None),
    begin: int | None = Query(None, description="Unix ms"),
    end: int | None = Query(None, description="Unix ms"),
    language: str = Query("zh-CN"),
    detail_lvl: str = Query("summary", description="brief / summary / full"),
    limit: int = Query(10, ge=1, le=50),
    after: str | None = Query(None, description="Pagination cursor"),
) -> dict[str, Any]:
    try:
        return await okx_orbit.get_latest_news(
            coins=coins,
            importance=importance,
            platform=platform,
            begin=begin,
            end=end,
            language=language,
            detail_lvl=detail_lvl,
            limit=limit,
            after=after,
        )
    except Exception as exc:
        return {"items": [], "count": 0, "error": f"Failed to fetch OKX latest news: {exc}"}


@router.get("/okx/important")
async def okx_important_news(
    coins: str | None = Query(None, description="Comma-separated symbols, e.g. BTC,ETH"),
    platform: str | None = Query(None),
    begin: int | None = Query(None, description="Unix ms"),
    end: int | None = Query(None, description="Unix ms"),
    language: str = Query("zh-CN"),
    detail_lvl: str = Query("summary", description="brief / summary / full"),
    limit: int = Query(10, ge=1, le=50),
) -> dict[str, Any]:
    try:
        return await okx_orbit.get_latest_news(
            coins=coins,
            importance="high",
            platform=platform,
            begin=begin,
            end=end,
            language=language,
            detail_lvl=detail_lvl,
            limit=limit,
        )
    except Exception as exc:
        return {"items": [], "count": 0, "error": f"Failed to fetch OKX important news: {exc}"}


@router.get("/okx/by-coin")
async def okx_news_by_coin(
    coins: str = Query(..., description="Comma-separated symbols, e.g. BTC,ETH"),
    importance: str | None = Query(None, description="high or low"),
    platform: str | None = Query(None),
    begin: int | None = Query(None, description="Unix ms"),
    end: int | None = Query(None, description="Unix ms"),
    language: str = Query("zh-CN"),
    detail_lvl: str = Query("summary", description="brief / summary / full"),
    limit: int = Query(10, ge=1, le=50),
) -> dict[str, Any]:
    try:
        return await okx_orbit.get_news_by_coin(
            coins=coins,
            importance=importance,
            platform=platform,
            begin=begin,
            end=end,
            language=language,
            detail_lvl=detail_lvl,
            limit=limit,
        )
    except Exception as exc:
        return {"items": [], "count": 0, "error": f"Failed to fetch OKX coin news: {exc}"}


@router.get("/okx/search")
async def okx_news_search(
    keyword: str | None = Query(None),
    coins: str | None = Query(None, description="Optional coin scope, e.g. BTC"),
    importance: str | None = Query(None, description="high or low"),
    platform: str | None = Query(None),
    sentiment: str | None = Query(None, description="bullish / bearish / neutral"),
    sort_by: str = Query("relevant", description="relevant / latest"),
    begin: int | None = Query(None, description="Unix ms"),
    end: int | None = Query(None, description="Unix ms"),
    language: str = Query("zh-CN"),
    detail_lvl: str = Query("summary", description="brief / summary / full"),
    limit: int = Query(10, ge=1, le=50),
    after: str | None = Query(None, description="Pagination cursor"),
) -> dict[str, Any]:
    try:
        return await okx_orbit.search_news(
            keyword=keyword,
            coins=coins,
            importance=importance,
            platform=platform,
            sentiment=sentiment,
            sort_by=sort_by,
            begin=begin,
            end=end,
            language=language,
            detail_lvl=detail_lvl,
            limit=limit,
            after=after,
        )
    except Exception as exc:
        return {"items": [], "count": 0, "error": f"Failed to search OKX news: {exc}"}


@router.get("/okx/detail/{article_id}")
async def okx_news_detail(
    article_id: str,
    language: str = Query("zh-CN"),
) -> dict[str, Any]:
    try:
        return await okx_orbit.get_news_detail(article_id, language=language)
    except Exception as exc:
        return {"item": None, "error": f"Failed to fetch OKX news detail: {exc}"}


@router.get("/okx/platforms")
async def okx_news_platforms() -> dict[str, Any]:
    try:
        return await okx_orbit.get_news_platforms()
    except Exception as exc:
        return {"items": [], "count": 0, "error": f"Failed to fetch OKX news platforms: {exc}"}


@router.get("/okx/coin-sentiment")
async def okx_coin_sentiment(
    coins: str = Query(..., description="Comma-separated symbols, e.g. BTC,ETH"),
    period: str = Query("24h", description="1h / 4h / 24h"),
    trend_points: int | None = Query(None, ge=1, le=48),
) -> dict[str, Any]:
    try:
        return await okx_orbit.get_coin_sentiment(
            coins=coins,
            period=period,
            trend_points=trend_points,
        )
    except Exception as exc:
        return {"items": [], "count": 0, "error": f"Failed to fetch OKX coin sentiment: {exc}"}


@router.get("/okx/sentiment-ranking")
async def okx_sentiment_ranking(
    period: str = Query("24h", description="1h / 4h / 24h"),
    sort_by: str = Query("hot", description="hot / bullish / bearish"),
    limit: int = Query(10, ge=1, le=50),
) -> dict[str, Any]:
    try:
        return await okx_orbit.get_sentiment_ranking(
            period=period,
            sort_by=sort_by,
            limit=limit,
        )
    except Exception as exc:
        return {"items": [], "count": 0, "error": f"Failed to fetch OKX sentiment ranking: {exc}"}


@router.get("/{category}")
async def get_news_by_category(
    category: str,
    count: int = Query(20, le=50),
    language: str = Query("en", description="Language code"),
) -> list[dict]:
    """Get news by category in specified language (live from API)."""
    return await fetch_desk3_news(category, count, language)
