"""Short-term price predictor combining technical analysis and AI."""

from __future__ import annotations

import logging
from typing import Any

from app.market.sources import binance
from app.analysis.indicators import analyze_klines
from app.analysis.strategy import score_opportunity

logger = logging.getLogger("bitinfo.analysis.predictor")


async def predict_symbol(
    symbol: str = "BTC",
    interval: str = "15m",
    limit: int = 50,
    use_ai: bool = False,
) -> dict[str, Any]:
    """Run technical prediction on a symbol.

    Optionally use AI for enhanced reasoning.
    """
    klines = await binance.get_klines(f"{symbol}USDT", interval, limit)
    if not klines:
        return {"error": f"No kline data for {symbol}"}

    analysis = analyze_klines(klines)
    if "error" in analysis:
        return analysis

    strategy = score_opportunity(analysis)

    result = {
        "symbol": symbol,
        "interval": interval,
        "analysis": analysis,
        "strategy": strategy,
    }

    if use_ai:
        try:
            from app.common.ai_client import ai_predict_direction

            ai_result = await ai_predict_direction({
                "symbol": symbol,
                "price": analysis["price"],
                "indicators": analysis["indicators"],
                "technical_direction": analysis["direction"],
                "technical_confidence": analysis["confidence"],
                "strategy_score": strategy["score"],
            })
            result["ai_prediction"] = ai_result
        except Exception:
            logger.warning("AI prediction failed for %s", symbol, exc_info=True)
            result["ai_prediction"] = None

    return result
