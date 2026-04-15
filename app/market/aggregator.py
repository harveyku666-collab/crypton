"""Multi-source aggregator — combines data from all sources with fallback."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.market.sources import desk3, binance, coingecko

logger = logging.getLogger("bitinfo.market")


async def get_market_overview() -> dict[str, Any]:
    """Aggregate core market data from multiple sources."""
    tasks = {
        "desk3_prices": desk3.get_core_prices(),
        "desk3_fear_greed": desk3.get_fear_greed(),
        "desk3_dominance": desk3.get_dominance(),
        "desk3_trending": desk3.get_trending(10),
        "gecko_global": coingecko.get_global(),
        "gecko_trending": coingecko.get_trending(),
        "gecko_fear_greed": coingecko.get_fear_greed(),
    }
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    data = {}
    for k, v in zip(tasks.keys(), results):
        data[k] = None if isinstance(v, BaseException) else v

    prices = data["desk3_prices"] or {}
    fear = data["desk3_fear_greed"] or data["gecko_fear_greed"]
    dominance = data["desk3_dominance"]
    global_data = data["gecko_global"]

    return {
        "prices": prices,
        "fear_greed": fear,
        "dominance": dominance,
        "global": global_data,
        "trending_desk3": data["desk3_trending"],
        "trending_gecko": data["gecko_trending"],
    }


async def get_symbol_price(symbol: str) -> dict[str, Any] | None:
    """Get price for a single symbol, trying Binance first then Desk3."""
    ticker = await binance.get_ticker_24h(f"{symbol}USDT")
    if ticker:
        return {
            "symbol": symbol,
            "price": float(ticker.get("lastPrice", 0)),
            "change_pct": float(ticker.get("priceChangePercent", 0)),
            "volume": float(ticker.get("quoteVolume", 0)),
            "high": float(ticker.get("highPrice", 0)),
            "low": float(ticker.get("lowPrice", 0)),
            "source": "binance",
        }
    desk3_prices = await desk3.get_prices(f"{symbol}USDT")
    for item in desk3_prices:
        if item.get("s") == f"{symbol}USDT":
            return {
                "symbol": symbol,
                "price": float(item.get("c", 0)),
                "change_pct": float(item.get("P", 0)),
                "volume": float(item.get("q", 0)),
                "source": "desk3",
            }
    return None
