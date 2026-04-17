"""DeFi yield scanner — wraps defi_llama.scan_yields with DB persistence."""

from __future__ import annotations

import logging
from typing import Any

from app.market.sources.defi_llama import scan_yields
from app.common.database import async_session, db_available
from app.common.models import DefiYield

logger = logging.getLogger("bitinfo.analysis.yield")


async def scan_and_store(
    min_apy: float = 1.0,
    min_tvl: float = 1_000_000,
    chain: str | None = None,
    symbol: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    results = await scan_yields(min_apy, min_tvl, chain, symbol, limit)

    if db_available():
        try:
            async with async_session() as session:
                for r in results:
                    dy = DefiYield(
                        pool=r["pool"],
                        project=r["project"],
                        chain=r["chain"],
                        symbol=r["symbol"],
                        apy=r["apy"],
                        tvl=r["tvl"],
                    )
                    session.add(dy)
                await session.commit()
        except Exception:
            logger.debug("DB store skipped for DeFi yields", exc_info=True)

    return results
