"""Strategy runner — dispatches trading signals to exchange adapters."""

from __future__ import annotations

import logging
from typing import Any

from app.trading.exchanges.base import ExchangeBase, OrderResult
from app.trading.risk_manager import RiskManager
from app.common.database import async_session, db_available
from app.common.models import TradeLog

logger = logging.getLogger("bitinfo.trading.strategy")


class StrategyRunner:
    def __init__(self, exchange: ExchangeBase, risk: RiskManager | None = None):
        self.exchange = exchange
        self.risk = risk or RiskManager()

    async def execute_signal(
        self,
        symbol: str,
        direction: str,
        confidence: float,
        price: float,
        balance: float | None = None,
    ) -> dict[str, Any]:
        """Execute a trading signal with risk management.

        Returns execution details or rejection reason.
        """
        check = self.risk.check_signal(direction, confidence, price, balance)
        if not check["approved"]:
            return {"executed": False, "reason": check["reason"]}

        quantity = check["quantity"]
        side = "BUY" if direction == "UP" else "SELL"

        result = await self.exchange.place_order(symbol, side, quantity)

        if db_available():
            try:
                async with async_session() as session:
                    session.add(TradeLog(
                        exchange=self.exchange.name,
                        symbol=symbol,
                        side=side,
                        price=price,
                        quantity=quantity,
                        strategy=f"signal_{confidence:.0f}pct",
                    ))
                    await session.commit()
            except Exception:
                logger.debug("DB store skipped for trade log", exc_info=True)

        return {
            "executed": result.success,
            "order_id": result.order_id,
            "side": side,
            "quantity": quantity,
            "stop_loss": check.get("stop_loss"),
            "error": result.error,
        }
