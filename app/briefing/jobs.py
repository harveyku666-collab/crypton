"""Briefing scheduled jobs — daily / weekly / monthly report generation."""

from __future__ import annotations

import logging

from app.common.database import async_session, db_available
from app.common.models import Briefing
from app.briefing.generator import generate_briefing

logger = logging.getLogger("bitinfo.briefing.jobs")

REPORT_LANGUAGES = ["zh", "en"]


async def _generate_and_store(period: str) -> None:
    """Generate briefings in all languages and persist to DB."""
    if not db_available():
        return
    for lang in REPORT_LANGUAGES:
        try:
            data = await generate_briefing(period=period, language=lang)
            async with async_session() as session:
                briefing = Briefing(
                    period=period,
                    language=lang,
                    title=data["title"],
                    content_json=data,
                    content_text=data.get("content_text"),
                )
                session.add(briefing)
                await session.commit()
            logger.info("Generated %s briefing (%s)", period, lang)
        except Exception:
            logger.exception("Failed to generate %s briefing (%s)", period, lang)


async def generate_daily_briefing() -> None:
    await _generate_and_store("daily")


async def generate_weekly_briefing() -> None:
    await _generate_and_store("weekly")


async def generate_monthly_briefing() -> None:
    await _generate_and_store("monthly")


def register_briefing_jobs() -> None:
    from app.common.scheduler import add_cron_job, add_interval_job

    add_cron_job(generate_daily_briefing, hour=8, minute=0, job_id="briefing.daily")
    add_cron_job(generate_weekly_briefing, day_of_week="mon", hour=8, minute=30, job_id="briefing.weekly")
    add_cron_job(generate_monthly_briefing, day=1, hour=9, minute=0, job_id="briefing.monthly")
    logger.info("Briefing jobs registered (daily@08:00, weekly@Mon 08:30, monthly@1st 09:00)")
