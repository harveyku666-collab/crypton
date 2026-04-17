"""News collection scheduled jobs — multi-language, deduplicated DB storage."""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.common.database import async_session, db_available
from app.common.models import NewsItem
from app.news.fetcher import fetch_multilang_news

logger = logging.getLogger("bitinfo.news.jobs")

COLLECT_LANGUAGES = ["en", "zh"]
COLLECT_CATEGORIES = ["crypto", "policy"]


async def collect_all_news() -> None:
    """Fetch news in all configured languages and save to DB (skip duplicates)."""
    if not db_available():
        return
    try:
        all_data = await fetch_multilang_news(COLLECT_LANGUAGES, COLLECT_CATEGORIES, count=20)
        total = 0
        skipped = 0

        async with async_session() as session:
            for lang, categories in all_data.items():
                for category, items in categories.items():
                    for item in items:
                        ext_id = item.get("external_id")
                        if ext_id:
                            existing = await session.execute(
                                select(NewsItem.id).where(NewsItem.external_id == ext_id)
                            )
                            if existing.scalar_one_or_none() is not None:
                                skipped += 1
                                continue

                        news = NewsItem(
                            title=item["title"][:500],
                            content=item.get("description"),
                            source=item["source"],
                            category=category,
                            language=lang,
                            sentiment=item.get("sentiment", "neutral"),
                            importance=item.get("importance", "normal"),
                            published_at=str(item["published_at"]) if item.get("published_at") else None,
                            url=item.get("url"),
                            external_id=ext_id,
                        )
                        session.add(news)
                        total += 1
            await session.commit()
        logger.info("Collected %d news items (%d duplicates skipped)", total, skipped)
    except Exception:
        logger.exception("Failed to collect news")


def register_news_jobs() -> None:
    from app.common.scheduler import add_interval_job

    add_interval_job(collect_all_news, hours=1, job_id="news.collect")
    logger.info("News jobs registered")
