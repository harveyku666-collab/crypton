"""Briefing API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import select, desc

from app.briefing.generator import generate_briefing

router = APIRouter(prefix="/briefing", tags=["briefing"])


@router.get("/live")
async def get_live_briefing(
    language: str = Query("zh", description="Language: zh, en, ja, ..."),
    period: str = Query("daily", description="Report period: daily, weekly, monthly"),
) -> dict[str, Any]:
    """Generate a live briefing on demand (real-time data)."""
    return await generate_briefing(period=period, language=language)


@router.get("/live/text")
async def get_live_briefing_text(
    language: str = Query("zh"),
    period: str = Query("daily"),
) -> str:
    """Generate a live briefing and return plain text."""
    data = await generate_briefing(period=period, language=language)
    return data.get("content_text", "")


@router.get("/history")
async def get_briefing_history(
    language: str = Query("zh"),
    period: str = Query("daily"),
    limit: int = Query(10, le=50),
) -> list[dict[str, Any]]:
    """Get stored briefing reports from database."""
    from app.common.database import async_session
    from app.common.models import Briefing

    try:
        async with async_session() as session:
            stmt = (
                select(Briefing)
                .where(Briefing.language == language, Briefing.period == period)
                .order_by(desc(Briefing.created_at))
                .limit(limit)
            )
            result = await session.execute(stmt)
            items = result.scalars().all()
            return [
                {
                    "id": b.id,
                    "period": b.period,
                    "language": b.language,
                    "title": b.title,
                    "generated_at": str(b.created_at),
                    "content": b.content_json,
                }
                for b in items
            ]
    except Exception:
        return [{"error": "Database not available. Use /live for real-time briefing."}]


@router.post("/generate")
async def trigger_briefing(
    language: str = Query("zh"),
    period: str = Query("daily"),
    save: bool = Query(True, description="Save to database"),
) -> dict[str, Any]:
    """Manually trigger briefing generation and optionally save to DB."""
    data = await generate_briefing(period=period, language=language)

    if save:
        try:
            from app.common.database import async_session
            from app.common.models import Briefing

            async with async_session() as session:
                briefing = Briefing(
                    period=period,
                    language=language,
                    title=data["title"],
                    content_json=data,
                    content_text=data.get("content_text"),
                )
                session.add(briefing)
                await session.commit()
                data["saved_to_db"] = True
        except Exception:
            data["saved_to_db"] = False
            data["db_error"] = "Database not available"

    return data
