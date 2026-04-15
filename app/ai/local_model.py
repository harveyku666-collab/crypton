"""Local model inference — placeholder for future self-evolving AI.

Phase 3: Train on historical predictions + actual outcomes to build
a local model that improves over time.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("bitinfo.ai.local")


async def predict_local(features: dict[str, Any]) -> dict[str, Any]:
    """Run local model prediction.

    TODO Phase 3:
    - Collect prediction+outcome pairs from DB
    - Train lightweight model (XGBoost / LightGBM / small transformer)
    - Serve predictions locally without cloud API dependency
    - Compare accuracy vs cloud model and auto-switch
    """
    return {
        "direction": "NEUTRAL",
        "confidence": 0,
        "reasoning": "Local model not yet trained. Use cloud inference.",
        "model": "placeholder",
    }
