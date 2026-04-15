"""Risk management — position sizing, stop-loss, and safety checks."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("bitinfo.trading.risk")


class RiskManager:
    def __init__(
        self,
        max_position_pct: float = 0.1,
        stop_loss_pct: float = 0.05,
        min_confidence: float = 60.0,
        max_leverage: int = 3,
    ):
        self.max_position_pct = max_position_pct
        self.stop_loss_pct = stop_loss_pct
        self.min_confidence = min_confidence
        self.max_leverage = max_leverage

    def check_signal(
        self,
        direction: str,
        confidence: float,
        price: float,
        balance: float | None = None,
    ) -> dict[str, Any]:
        if direction == "NEUTRAL":
            return {"approved": False, "reason": "NEUTRAL signal — no action"}

        if confidence < self.min_confidence:
            return {"approved": False, "reason": f"Confidence {confidence}% < minimum {self.min_confidence}%"}

        if balance is None:
            balance = 10000.0

        position_value = balance * self.max_position_pct
        quantity = position_value / price if price > 0 else 0

        if direction == "UP":
            stop_loss = price * (1 - self.stop_loss_pct)
        else:
            stop_loss = price * (1 + self.stop_loss_pct)

        return {
            "approved": True,
            "quantity": round(quantity, 6),
            "position_value": round(position_value, 2),
            "stop_loss": round(stop_loss, 2),
            "risk_pct": self.stop_loss_pct * 100,
            "reason": "Signal approved",
        }
