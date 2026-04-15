"""Investment strategy scorer — ported from crypto-investment-strategist."""

from __future__ import annotations

from typing import Any


def score_opportunity(analysis: dict[str, Any], market_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Score a trading opportunity based on technical analysis + market context.

    Returns a composite score 0-100 with actionable recommendation.
    """
    ind = analysis.get("indicators", {})
    rsi = ind.get("rsi")
    macd = ind.get("macd", {})
    boll = ind.get("bollinger", {})
    momentum = ind.get("momentum")
    vol_ratio = ind.get("volume_ratio", 1.0)

    tech_score = 50.0

    if rsi is not None:
        if rsi < 30:
            tech_score += 15
        elif rsi < 45:
            tech_score += 8
        elif rsi > 70:
            tech_score -= 15
        elif rsi > 55:
            tech_score -= 5

    if macd.get("histogram") is not None:
        hist = macd["histogram"]
        if hist > 0:
            tech_score += 10
        else:
            tech_score -= 10

    if momentum is not None:
        if momentum > 2:
            tech_score += 8
        elif momentum < -2:
            tech_score -= 8

    if vol_ratio > 2:
        tech_score += 5
    elif vol_ratio < 0.5:
        tech_score -= 5

    tech_score = max(0, min(100, tech_score))

    if tech_score >= 70:
        action = "BUY"
        note = "Strong bullish signals — consider scaling in"
    elif tech_score >= 55:
        action = "HOLD"
        note = "Mildly bullish — hold existing positions"
    elif tech_score >= 45:
        action = "NEUTRAL"
        note = "No clear direction — wait for confirmation"
    elif tech_score >= 30:
        action = "REDUCE"
        note = "Bearish signals — consider reducing exposure"
    else:
        action = "AVOID"
        note = "Strong bearish signals — avoid new longs"

    return {
        "score": round(tech_score, 1),
        "action": action,
        "note": note,
        "direction": analysis.get("direction", "NEUTRAL"),
        "confidence": analysis.get("confidence", 0),
    }
