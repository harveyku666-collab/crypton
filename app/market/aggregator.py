"""Multi-source aggregator — Surf primary, Desk3/CoinGecko/Binance fallback."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.market.sources import desk3, binance, coingecko, surf

logger = logging.getLogger("bitinfo.market")


def _safe_float(value: Any) -> float | None:
    try:
        if value in {None, ""}:
            return None
        return float(value)
    except Exception:
        return None


async def get_market_overview() -> dict[str, Any]:
    """Aggregate core market data — Surf first, legacy fallback."""
    tasks = {
        "surf_fear_greed": surf.get_fear_greed(),
        "surf_ranking": surf.get_market_ranking(20),
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
    fear = data["surf_fear_greed"] or data["desk3_fear_greed"] or data["gecko_fear_greed"]
    dominance = data["desk3_dominance"]
    global_data = data["gecko_global"]

    return {
        "prices": prices,
        "fear_greed": fear,
        "dominance": dominance,
        "global": global_data,
        "trending_desk3": data["desk3_trending"],
        "trending_gecko": data["gecko_trending"],
        "surf_ranking": data["surf_ranking"],
    }


async def get_symbol_price(symbol: str) -> dict[str, Any] | None:
    """Get price for a single symbol — Surf > Binance > Desk3."""
    normalized_symbol = str(symbol or "").strip().upper()
    if not normalized_symbol:
        return None

    try:
        surf_price = await surf.get_price(normalized_symbol)
    except Exception:
        logger.debug("Surf price lookup failed for %s", normalized_symbol, exc_info=True)
        surf_price = None
    if isinstance(surf_price, dict):
        price = _safe_float(surf_price.get("price"))
        if price is not None and price > 0:
            return {
                **surf_price,
                "symbol": normalized_symbol,
                "price": price,
                "source": str(surf_price.get("source") or "surf"),
            }

    try:
        ticker = await binance.get_ticker_24h(f"{normalized_symbol}USDT")
    except Exception:
        logger.debug("Binance price lookup failed for %s", normalized_symbol, exc_info=True)
        ticker = None
    if isinstance(ticker, dict):
        price = _safe_float(ticker.get("lastPrice"))
        if price is not None and price > 0:
            return {
                "symbol": normalized_symbol,
                "price": price,
                "change_pct": _safe_float(ticker.get("priceChangePercent")),
                "volume": _safe_float(ticker.get("quoteVolume")),
                "high": _safe_float(ticker.get("highPrice")),
                "low": _safe_float(ticker.get("lowPrice")),
                "source": "binance",
            }

    try:
        desk3_prices = await desk3.get_prices(f"{normalized_symbol}USDT")
    except Exception:
        logger.debug("Desk3 price lookup failed for %s", normalized_symbol, exc_info=True)
        desk3_prices = []
    for item in desk3_prices if isinstance(desk3_prices, list) else []:
        if item.get("s") == f"{normalized_symbol}USDT":
            price = _safe_float(item.get("c"))
            if price is None or price <= 0:
                continue
            return {
                "symbol": normalized_symbol,
                "price": price,
                "change_pct": _safe_float(item.get("P")),
                "volume": _safe_float(item.get("q")),
                "source": "desk3",
            }

    try:
        gecko_price = await coingecko.get_price_by_symbol(normalized_symbol)
    except Exception:
        logger.debug("CoinGecko price lookup failed for %s", normalized_symbol, exc_info=True)
        gecko_price = None
    if isinstance(gecko_price, dict):
        price = _safe_float(gecko_price.get("price"))
        if price is not None and price > 0:
            return {
                **gecko_price,
                "symbol": normalized_symbol,
                "price": price,
                "source": str(gecko_price.get("source") or "coingecko"),
            }

    return None
