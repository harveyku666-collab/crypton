"""Analysis API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.analysis.predictor import predict_symbol
from app.analysis.funding_scan import scan_and_store as scan_funding
from app.analysis.yield_scan import scan_and_store as scan_defi
from app.analysis.btc_predictor import predict_short_term

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.get("/predict/{symbol}")
async def predict(
    symbol: str,
    interval: str = Query("15m"),
    limit: int = Query(50, le=1000),
    use_ai: bool = Query(False),
) -> dict[str, Any]:
    return await predict_symbol(symbol.upper(), interval, limit, use_ai)


@router.get("/funding-scan")
async def funding_scan(
    min_rate: float = Query(0.0005),
    min_volume: float = Query(10_000_000),
) -> list[dict]:
    return await scan_funding(min_rate, min_volume)


@router.get("/defi-yields")
async def defi_yields(
    min_apy: float = Query(1.0),
    min_tvl: float = Query(1_000_000),
    chain: str | None = Query(None),
    symbol: str | None = Query(None),
    limit: int = Query(50, le=200),
) -> list[dict]:
    return await scan_defi(min_apy, min_tvl, chain, symbol, limit)


@router.get("/btc-predict")
async def btc_quant_predict(
    symbol: str = Query("BTC", description="币种符号，如 BTC、ETH、SOL"),
    interval: str = Query("15m", description="K线周期: 1m/5m/15m/1h/4h"),
    limit: int = Query(50, le=200, description="K线数量"),
) -> dict[str, Any]:
    """BTC 量化短线预测 — 多因子评分系统

    基于 RSI + MACD + 布林带 + 动量 + 成交量的综合评分，
    输出方向预测、置信度、止损止盈建议。
    """
    return await predict_short_term(symbol.upper(), interval, limit)
