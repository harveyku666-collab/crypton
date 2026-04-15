"""Trading API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

router = APIRouter(prefix="/trading", tags=["trading"])


class TradeSignal(BaseModel):
    symbol: str
    direction: str
    confidence: float
    price: float
    exchange: str = "binance"


@router.post("/execute")
async def execute_trade(signal: TradeSignal) -> dict[str, Any]:
    """Execute a trade based on an AI/analysis signal.

    Requires exchange API keys to be configured.
    """
    from app.trading.exchanges.binance import BinanceExchange
    from app.trading.exchanges.okx import OKXExchange
    from app.trading.strategy_runner import StrategyRunner
    from app.config import settings

    if signal.exchange == "okx":
        exchange = OKXExchange(demo=True)
    else:
        exchange = BinanceExchange(testnet=True)

    runner = StrategyRunner(exchange)
    return await runner.execute_signal(
        symbol=signal.symbol.upper(),
        direction=signal.direction.upper(),
        confidence=signal.confidence,
        price=signal.price,
    )


@router.get("/status")
async def trading_status() -> dict[str, Any]:
    return {
        "enabled": False,
        "note": "Configure exchange API keys in .env to enable live trading. Testnet mode by default.",
        "supported_exchanges": ["binance", "okx"],
    }
