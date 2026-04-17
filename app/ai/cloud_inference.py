"""Cloud AI inference — sends market data to LLM for direction prediction."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.common.ai_client import ai_chat
from app.common.database import async_session, db_available
from app.common.models import AIDecision

logger = logging.getLogger("bitinfo.ai.cloud")


async def predict_with_context(
    symbol: str,
    market_data: dict[str, Any],
    analysis_data: dict[str, Any],
) -> dict[str, Any]:
    """Send comprehensive market context to cloud AI for prediction."""

    system_prompt = """You are a senior crypto quantitative analyst. Given:
- Current market data (prices, sentiment, dominance)
- Technical analysis (RSI, MACD, Bollinger, momentum)

Provide a prediction in strict JSON format:
{
    "direction": "UP|DOWN|NEUTRAL",
    "confidence": 0-100,
    "timeframe": "1h|4h|1d",
    "entry_zone": [low, high],
    "stop_loss": price,
    "take_profit": [tp1, tp2],
    "reasoning": "brief explanation"
}"""

    user_msg = f"""Symbol: {symbol}

Market Data:
{json.dumps(market_data, indent=2, default=str)}

Technical Analysis:
{json.dumps(analysis_data, indent=2, default=str)}

Provide your prediction:"""

    raw = await ai_chat(system_prompt, user_msg, temperature=0.2)

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {"direction": "NEUTRAL", "confidence": 0, "reasoning": raw}

    if db_available():
        try:
            async with async_session() as session:
                session.add(AIDecision(
                    symbol=symbol,
                    input_features={"market": market_data, "analysis": analysis_data},
                    reasoning=result.get("reasoning"),
                    decision=result.get("direction", "NEUTRAL"),
                    confidence=result.get("confidence"),
                ))
                await session.commit()
        except Exception:
            logger.debug("DB store skipped for AI decision", exc_info=True)

    return result
