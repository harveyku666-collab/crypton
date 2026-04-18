"""Analysis API routes."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Query

from app.analysis.indicators import analyze_symbol_technical
from app.analysis.predictor import predict_symbol
from app.analysis.funding_scan import scan_and_store as scan_funding
from app.analysis.strategy import score_opportunity
from app.analysis.yield_scan import scan_and_store as scan_defi
from app.analysis.btc_predictor import predict_short_term
from app.analysis.okx_market_intel import build_market_intel_master
from app.market.sources import okx
from app.news import okx_orbit

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.get("/indicators")
async def technical_indicators(
    symbol: str = Query("BTC", description="币种符号，如 BTC、ETH、SOL"),
    interval: str = Query("4h", description="K线周期: 15m/1h/4h/1d"),
    limit: int = Query(120, ge=30, le=300, description="K线数量"),
    include_multi_timeframes: bool = Query(True, description="是否返回多周期摘要"),
) -> dict[str, Any]:
    normalized_symbol = symbol.upper()
    primary = await analyze_symbol_technical(normalized_symbol, interval, limit)
    if "error" in primary:
        return primary

    primary["strategy"] = score_opportunity(primary.get("analysis", {}))

    if include_multi_timeframes:
        intervals = ["15m", "1h", "4h", "1d"]
        results = await asyncio.gather(*[
            analyze_symbol_technical(
                normalized_symbol,
                tf,
                limit if tf == interval else (90 if tf == "1d" else 120),
            )
            for tf in intervals
        ])
        summary: dict[str, Any] = {}
        for tf, snapshot in zip(intervals, results):
            if "error" in snapshot:
                continue
            summary[tf] = {
                "price": snapshot.get("price"),
                "direction": snapshot.get("direction"),
                "confidence": snapshot.get("confidence"),
                "trend": snapshot.get("trend"),
                "rsi": snapshot.get("rsi"),
                "rsi_status": snapshot.get("rsi_status"),
                "momentum": snapshot.get("momentum"),
                "volume_ratio": snapshot.get("volume_ratio"),
                "moving_averages": snapshot.get("moving_averages", {}),
                "strategy": score_opportunity(snapshot.get("analysis", {})),
            }
        primary["multi_timeframes"] = summary

    return primary


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


@router.get("/okx/indicators")
async def okx_indicator_list() -> list[dict[str, str]]:
    """List OKX-supported public indicator names."""
    return await okx.list_indicators()


@router.get("/okx/indicator")
async def okx_indicator(
    inst_id: str = Query("BTC-USDT-SWAP"),
    indicator: str = Query("rsi"),
    bar: str = Query("1H"),
    params: str | None = Query(None, description="Comma-separated numeric params, e.g. 12,26,9"),
    return_list: bool = Query(False),
    limit: int = Query(10, ge=1, le=100),
    backtest_time: int | None = Query(None),
) -> dict[str, Any]:
    parsed_params: list[float] | None = None
    if params:
        parsed_params = []
        for item in params.split(","):
            item = item.strip()
            if not item:
                continue
            parsed_params.append(float(item))
    return await okx.get_indicator(
        inst_id,
        indicator,
        bar=bar,
        params=parsed_params,
        return_list=return_list,
        limit=limit,
        backtest_time=backtest_time,
    )


@router.get("/okx/market-intelligence")
async def okx_market_intelligence(
    inst_id: str = Query("BTC-USDT-SWAP"),
    candle_bar: str = Query("1H"),
    orderbook_depth: int = Query(20, ge=1, le=400),
    trade_limit: int = Query(20, ge=1, le=100),
    oi_bar: str = Query("1H"),
    oi_limit: int = Query(30, ge=2, le=200),
) -> dict[str, Any]:
    """Replicated OKX public intelligence snapshot for downstream pages and agents.

    This focuses on public market data + analysis only. It does not expose
    account or trading actions.
    """
    return await okx.build_market_intelligence(
        inst_id,
        candle_bar=candle_bar,
        orderbook_depth=orderbook_depth,
        trade_limit=trade_limit,
        oi_bar=oi_bar,
        oi_limit=oi_limit,
    )


@router.get("/okx/overview")
async def okx_overview(
    inst_id: str = Query("BTC-USDT-SWAP"),
    candle_bar: str = Query("1H"),
    orderbook_depth: int = Query(20, ge=1, le=400),
    trade_limit: int = Query(20, ge=1, le=100),
    oi_bar: str = Query("1H"),
    oi_limit: int = Query(30, ge=2, le=200),
    language: str = Query("zh-CN"),
    detail_lvl: str = Query("summary"),
    platform: str | None = Query(None),
    news_limit: int = Query(6, ge=1, le=20),
    important_limit: int = Query(5, ge=1, le=20),
    sentiment_period: str = Query("24h"),
    trend_points: int | None = Query(12, ge=1, le=48),
    ranking_limit: int = Query(8, ge=1, le=20),
) -> dict[str, Any]:
    base_symbol = inst_id.split("-")[0].upper()

    tasks = await asyncio.gather(
        okx.build_market_intelligence(
            inst_id,
            candle_bar=candle_bar,
            orderbook_depth=orderbook_depth,
            trade_limit=trade_limit,
            oi_bar=oi_bar,
            oi_limit=oi_limit,
        ),
        okx_orbit.get_news_by_coin(
            coins=base_symbol,
            platform=platform,
            language=language,
            detail_lvl=detail_lvl,
            limit=news_limit,
        ),
        okx_orbit.get_latest_news(
            importance="high",
            platform=platform,
            language=language,
            detail_lvl=detail_lvl,
            limit=important_limit,
        ),
        okx_orbit.get_coin_sentiment(
            coins=base_symbol,
            period=sentiment_period,
            trend_points=trend_points,
        ),
        okx_orbit.get_sentiment_ranking(
            period=sentiment_period,
            sort_by="hot",
            limit=ranking_limit,
        ),
        return_exceptions=True,
    )

    market, coin_news, important_news, coin_sentiment, ranking = tasks

    def _section(value: Any, label: str) -> Any:
        if isinstance(value, Exception):
            return {"error": f"Failed to load {label}: {value}"}
        return value

    return {
        "instId": inst_id,
        "coin": base_symbol,
        "market": _section(market, "market intelligence"),
        "coin_news": _section(coin_news, "coin news"),
        "important_news": _section(important_news, "important news"),
        "coin_sentiment": _section(coin_sentiment, "coin sentiment"),
        "sentiment_ranking": _section(ranking, "sentiment ranking"),
    }


@router.get("/okx/market-intel")
async def okx_market_intel_master(
    symbol: str = Query("BTC", description="基础币种，或完整 instId"),
    market_type: str = Query("SWAP", description="SWAP / SPOT"),
    timeframe: str = Query("1H", description="1H / 4H / 1D"),
    language: str = Query("zh-CN", description="zh-CN / en-US"),
    keyword: str | None = Query(None, description="关键词研究，如 ETF、AI、监管"),
    platform: str | None = Query(None, description="Orbit platform source filter"),
    news_limit: int = Query(8, ge=1, le=20),
    important_limit: int = Query(6, ge=1, le=20),
    search_limit: int = Query(12, ge=1, le=24),
    ranking_limit: int = Query(8, ge=1, le=20),
) -> dict[str, Any]:
    """Replicate the public-facing OKX market-intel skill workflow."""
    return await build_market_intel_master(
        symbol=symbol,
        market_type=market_type,
        timeframe=timeframe,
        language=language,
        keyword=keyword,
        platform=platform,
        news_limit=news_limit,
        important_limit=important_limit,
        search_limit=search_limit,
        ranking_limit=ranking_limit,
    )
