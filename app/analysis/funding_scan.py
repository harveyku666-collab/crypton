"""Funding rate scanner — wraps binance.scan_funding_rates with DB persistence."""

from __future__ import annotations

import logging
from typing import Any

from app.market.sources.binance import scan_funding_rates
from app.common.database import async_session, db_available
from app.common.models import FundingRate

logger = logging.getLogger("bitinfo.analysis.funding")


async def scan_and_store(min_abs_rate: float = 0.0005, min_volume: float = 10_000_000) -> list[dict[str, Any]]:
    results = await scan_funding_rates(min_abs_rate, min_volume)

    if not db_available():
        return results

    try:
        async with async_session() as session:
            for r in results:
                fr = FundingRate(
                    symbol=r["symbol"],
                    rate=r["rate"],
                    predicted_rate=None,
                    price=r["price"],
                    volume_24h=r["volume_24h"],
                )
                session.add(fr)
            await session.commit()
    except Exception:
        logger.debug("DB store skipped for funding rates", exc_info=True)

    return results
