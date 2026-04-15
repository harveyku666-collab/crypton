"""Scheduled market data collection jobs."""

from __future__ import annotations

import logging

from app.common.database import async_session
from app.common.models import PriceTick, NewsItem
from app.market.sources import desk3

logger = logging.getLogger("bitinfo.market.jobs")


async def collect_price_ticks() -> None:
    """Collect BTC/ETH/SOL prices and store to DB."""
    try:
        prices = await desk3.get_core_prices()
        async with async_session() as session:
            for symbol, data in prices.items():
                tick = PriceTick(
                    symbol=symbol,
                    price=data["price"],
                    change_pct=data["change_pct"],
                    source="desk3",
                )
                session.add(tick)
            await session.commit()
        logger.info("Collected %d price ticks", len(prices))
    except Exception:
        logger.exception("Failed to collect price ticks")


async def collect_news() -> None:
    """Collect latest crypto news and store to DB."""
    try:
        from app.market.sources.desk3 import HEADERS as desk3_headers
        from app.common.http_client import fetch_json

        for cat, catid in [("crypto", 1), ("policy", 3)]:
            data = await fetch_json(
                "https://api1.desk3.io/v1/news/list",
                params={"catid": catid, "page": 1, "rows": 10},
                headers=desk3_headers,
            )
            items = data.get("data", {}).get("list", []) if data.get("code") == 0 else []
            async with async_session() as session:
                for item in items:
                    news = NewsItem(
                        title=item.get("title", "")[:500],
                        content=item.get("description"),
                        source="desk3",
                        category=cat,
                        published_at=item.get("published_at"),
                        url=item.get("url"),
                    )
                    session.add(news)
                await session.commit()
            logger.info("Collected %d %s news items", len(items), cat)
    except Exception:
        logger.exception("Failed to collect news")


def register_market_jobs() -> None:
    """Register all market data collection jobs with the scheduler."""
    from app.common.scheduler import add_interval_job

    add_interval_job(collect_price_ticks, seconds=30, job_id="market.price_ticks")
    add_interval_job(collect_news, hours=1, job_id="market.news")
    logger.info("Market jobs registered")
