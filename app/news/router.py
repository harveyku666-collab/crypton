"""News API routes with multi-language support."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import select, desc

from app.news.fetcher import fetch_desk3_news, fetch_all_news, fetch_multilang_news, SUPPORTED_LANGUAGES

router = APIRouter(prefix="/news", tags=["news"])


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
    limit: int = Query(50, le=200),
) -> list[dict[str, Any]]:
    """Get stored news from database (historical) with sentiment/importance."""
    from app.common.database import async_session
    from app.common.models import NewsItem

    try:
        async with async_session() as session:
            stmt = select(NewsItem).where(NewsItem.language == language)
            if category:
                stmt = stmt.where(NewsItem.category == category)
            if sentiment:
                stmt = stmt.where(NewsItem.sentiment == sentiment)
            if importance:
                stmt = stmt.where(NewsItem.importance == importance)
            stmt = stmt.order_by(desc(NewsItem.created_at)).limit(limit)
            result = await session.execute(stmt)
            items = result.scalars().all()
            return [
                {
                    "id": n.id,
                    "title": n.title,
                    "content": n.content,
                    "source": n.source,
                    "category": n.category,
                    "language": n.language,
                    "sentiment": n.sentiment,
                    "importance": n.importance,
                    "published_at": n.published_at,
                    "url": n.url,
                    "stored_at": str(n.created_at),
                }
                for n in items
            ]
    except Exception:
        return [{"error": "Database not available. Use / endpoint for live news."}]


@router.get("/{category}")
async def get_news_by_category(
    category: str,
    count: int = Query(20, le=50),
    language: str = Query("en", description="Language code"),
) -> list[dict]:
    """Get news by category in specified language (live from API)."""
    return await fetch_desk3_news(category, count, language)
