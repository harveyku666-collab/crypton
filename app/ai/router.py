"""AI prediction API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.ai.feature_builder import build_features
from app.ai.cloud_inference import predict_with_context

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/predict/{symbol}")
async def ai_predict(symbol: str) -> dict[str, Any]:
    """Full AI-powered prediction: collect features -> cloud inference."""
    features = await build_features(symbol.upper())

    from app.config import settings
    if not settings.openai_api_key:
        return {
            "symbol": symbol.upper(),
            "features": features,
            "prediction": None,
            "note": "Set OPENAI_API_KEY in .env to enable AI predictions",
        }

    prediction = await predict_with_context(
        symbol.upper(),
        market_data={
            "price": features.get("price"),
            "fear_greed": features.get("fear_greed"),
            "dominance": features.get("dominance"),
        },
        analysis_data={
            "technical": features.get("technical"),
            "direction_signal": features.get("direction_signal"),
            "confidence": features.get("confidence"),
        },
    )
    return {
        "symbol": symbol.upper(),
        "features": features,
        "prediction": prediction,
    }


@router.get("/features/{symbol}")
async def get_features(symbol: str) -> dict[str, Any]:
    return await build_features(symbol.upper())
