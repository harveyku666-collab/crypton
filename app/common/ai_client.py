"""Unified AI client — cloud (OpenAI-compatible) now, local model later."""

from __future__ import annotations

import logging
from typing import Any

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger("bitinfo.ai")

_client: AsyncOpenAI | None = None


def get_ai_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.openai_api_key or "sk-placeholder",
            base_url=settings.openai_base_url,
        )
    return _client


async def ai_chat(
    system_prompt: str,
    user_message: str,
    *,
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 2000,
) -> str:
    client = get_ai_client()
    resp = await client.chat.completions.create(
        model=model or settings.ai_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content or ""


async def ai_predict_direction(market_data: dict[str, Any]) -> dict[str, Any]:
    """Ask AI for a price direction prediction based on market data."""
    import json

    system = (
        "You are a quantitative crypto analyst. Given market data, predict the short-term "
        "direction (UP/DOWN/NEUTRAL) with confidence (0-100) and brief reasoning. "
        "Respond in JSON: {\"direction\": \"UP|DOWN|NEUTRAL\", \"confidence\": 75, \"reasoning\": \"...\"}"
    )
    user_msg = f"Market data:\n{json.dumps(market_data, indent=2, default=str)}"

    raw = await ai_chat(system, user_msg)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"direction": "NEUTRAL", "confidence": 0, "reasoning": raw}
