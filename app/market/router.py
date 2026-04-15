"""Market data API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.market import aggregator
from app.market.sources import desk3, binance, coingecko, defi_llama

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/overview")
async def market_overview() -> dict[str, Any]:
    return await aggregator.get_market_overview()


@router.get("/price/{symbol}")
async def get_price(symbol: str) -> dict[str, Any]:
    result = await aggregator.get_symbol_price(symbol.upper())
    return result or {"error": f"No data for {symbol}"}


@router.get("/briefing")
async def full_briefing() -> dict[str, Any]:
    return await desk3.get_full_briefing()


@router.get("/fear-greed")
async def fear_greed() -> dict[str, Any]:
    desk3_fg = await desk3.get_fear_greed()
    gecko_fg = await coingecko.get_fear_greed()
    return {"desk3": desk3_fg, "coingecko": gecko_fg}


@router.get("/trending")
async def trending() -> dict[str, Any]:
    d3 = await desk3.get_trending(10)
    gecko = await coingecko.get_trending()
    return {"desk3": d3, "coingecko": gecko}


@router.get("/dominance")
async def dominance() -> dict[str, Any]:
    return await desk3.get_dominance() or {}


@router.get("/klines/{symbol}")
async def klines(
    symbol: str,
    interval: str = Query("15m"),
    limit: int = Query(50, le=1000),
) -> list:
    return await binance.get_klines(f"{symbol.upper()}USDT", interval, limit)


@router.get("/funding-rates")
async def funding_rates() -> list[dict]:
    return await binance.scan_funding_rates()


@router.get("/defi-yields")
async def defi_yields(
    min_apy: float = Query(1.0),
    min_tvl: float = Query(1_000_000),
    chain: str | None = Query(None),
    symbol: str | None = Query(None),
    limit: int = Query(50, le=200),
) -> list[dict]:
    return await defi_llama.scan_yields(min_apy, min_tvl, chain, symbol, limit)


@router.get("/cycles")
async def cycles() -> dict[str, Any]:
    return await desk3.get_cycles() or {}


@router.get("/cycle-indicators")
async def cycle_indicators() -> dict[str, Any]:
    return await desk3.get_cycle_indicators() or {}


@router.get("/calendar")
async def calendar(date: str | None = Query(None)) -> list[dict]:
    return await desk3.get_calendar(date)
