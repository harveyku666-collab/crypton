"""Scheduled analysis jobs."""

from __future__ import annotations

import logging

from app.common.database import async_session
from app.common.models import Indicator
from app.analysis.indicators import analyze_klines
from app.market.sources import binance

logger = logging.getLogger("bitinfo.analysis.jobs")

TRACKED_SYMBOLS = ["BTC", "ETH", "SOL"]


async def compute_and_store_indicators() -> None:
    try:
        for symbol in TRACKED_SYMBOLS:
            klines = await binance.get_klines(f"{symbol}USDT", "15m", 50)
            if not klines:
                continue
            analysis = analyze_klines(klines)
            if "error" in analysis:
                continue

            ind = analysis.get("indicators", {})
            async with async_session() as session:
                for itype, value in [
                    ("rsi", ind.get("rsi")),
                    ("macd_histogram", ind.get("macd", {}).get("histogram")),
                    ("momentum", ind.get("momentum")),
                    ("volume_ratio", ind.get("volume_ratio")),
                ]:
                    if value is not None:
                        session.add(Indicator(
                            symbol=symbol,
                            indicator_type=itype,
                            value=value,
                        ))
                await session.commit()
        logger.info("Indicators computed for %s", TRACKED_SYMBOLS)
    except Exception:
        logger.exception("Failed to compute indicators")


async def periodic_funding_scan() -> None:
    from app.analysis.funding_scan import scan_and_store
    try:
        results = await scan_and_store()
        logger.info("Funding scan: %d opportunities found", len(results))
    except Exception:
        logger.exception("Funding scan failed")


def register_analysis_jobs() -> None:
    from app.common.scheduler import add_interval_job

    add_interval_job(compute_and_store_indicators, minutes=5, job_id="analysis.indicators")
    add_interval_job(periodic_funding_scan, hours=4, job_id="analysis.funding")
    logger.info("Analysis jobs registered")
