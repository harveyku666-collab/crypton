"""Feature engineering — build AI input features from market + analysis data."""

from __future__ import annotations

import logging
from typing import Any

from app.market import aggregator
from app.market.sources import binance
from app.analysis.indicators import analyze_klines

logger = logging.getLogger("bitinfo.ai.features")


async def build_features(symbol: str = "BTC") -> dict[str, Any]:
    """Collect all available data for a symbol and structure it for AI input."""

    klines = await binance.get_klines(f"{symbol}USDT", "15m", 50)
    analysis = analyze_klines(klines) if klines else {}

    price_data = await aggregator.get_symbol_price(symbol)

    from app.market.sources import desk3
    fear = await desk3.get_fear_greed()
    dominance = await desk3.get_dominance()

    return {
        "symbol": symbol,
        "price": price_data,
        "technical": analysis.get("indicators") if "indicators" in analysis else None,
        "direction_signal": analysis.get("direction"),
        "confidence": analysis.get("confidence"),
        "fear_greed": fear,
        "dominance": dominance,
    }
