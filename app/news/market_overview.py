"""Market overview helpers extracted from the legacy crypto project."""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable

from app.common.cache import cached
from app.market import aggregator
from app.market.sources import binance, okx

DEFAULT_SYMBOLS = (
    "BTC",
    "ETH",
    "BNB",
    "SOL",
    "XRP",
    "ADA",
    "DOGE",
    "DOT",
    "POL",
    "LINK",
)


def _to_float(value: Any) -> float | None:
    try:
        if value in {None, ""}:
            return None
        return float(value)
    except Exception:
        return None


def _normalize_symbols(symbols: Iterable[str] | None, limit: int) -> list[str]:
    picked: list[str] = []
    seen: set[str] = set()
    for raw in symbols or DEFAULT_SYMBOLS:
        normalized = "".join(ch for ch in str(raw or "").upper() if ch.isalnum())[:16]
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        picked.append(normalized)
        if len(picked) >= max(limit, 1):
            break
    return picked or list(DEFAULT_SYMBOLS[: max(limit, 1)])


def _classify_sentiment(avg_change: float) -> tuple[str, str]:
    if avg_change > 2:
        return "bullish", "🐂 牛市"
    if avg_change < -2:
        return "bearish", "🐻 熊市"
    return "neutral", "➡️ 震荡"


def _normalize_binance_ticker(symbol: str, ticker: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "price": _to_float(ticker.get("lastPrice")),
        "bid": _to_float(ticker.get("bidPrice")),
        "ask": _to_float(ticker.get("askPrice")),
        "high_24h": _to_float(ticker.get("highPrice")),
        "low_24h": _to_float(ticker.get("lowPrice")),
        "volume_24h": _to_float(ticker.get("quoteVolume")),
        "change_24h": _to_float(ticker.get("priceChangePercent")),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "exchange": "binance",
    }


def _normalize_okx_ticker(symbol: str, ticker: dict[str, Any]) -> dict[str, Any]:
    last_price = _to_float(ticker.get("last"))
    open_24h = _to_float(ticker.get("open24h"))
    change_24h = None
    if last_price is not None and open_24h not in {None, 0}:
        change_24h = (last_price - open_24h) / open_24h * 100

    return {
        "symbol": symbol,
        "price": last_price,
        "bid": _to_float(ticker.get("bidPx")),
        "ask": _to_float(ticker.get("askPx")),
        "high_24h": _to_float(ticker.get("high24h")),
        "low_24h": _to_float(ticker.get("low24h")),
        "volume_24h": _to_float(ticker.get("volCcy24h")),
        "change_24h": change_24h,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "exchange": "okx",
    }


def _normalize_aggregate_snapshot(symbol: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "price": _to_float(snapshot.get("price")),
        "bid": _to_float(snapshot.get("bid")),
        "ask": _to_float(snapshot.get("ask")),
        "high_24h": _to_float(snapshot.get("high")),
        "low_24h": _to_float(snapshot.get("low")),
        "volume_24h": _to_float(snapshot.get("volume")),
        "change_24h": _to_float(snapshot.get("change_pct")),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "exchange": str(snapshot.get("source") or "aggregated"),
    }


async def _fetch_symbol_snapshot(symbol: str) -> dict[str, Any] | None:
    ticker = await binance.get_ticker_24h(f"{symbol}USDT")
    if isinstance(ticker, dict) and _to_float(ticker.get("lastPrice")) is not None:
        return _normalize_binance_ticker(symbol, ticker)

    ticker = await okx.get_ticker(f"{symbol}-USDT")
    if isinstance(ticker, dict) and _to_float(ticker.get("last")) is not None:
        return _normalize_okx_ticker(symbol, ticker)

    fallback = await aggregator.get_symbol_price(symbol)
    if isinstance(fallback, dict) and _to_float(fallback.get("price")) is not None:
        return _normalize_aggregate_snapshot(symbol, fallback)

    return None


@cached(ttl=30, prefix="news_market_overview")
async def get_market_overview_snapshot(
    *,
    symbols: tuple[str, ...] | None = None,
    limit: int = 10,
    movers: int = 3,
) -> dict[str, Any]:
    selected_symbols = _normalize_symbols(symbols, limit)
    results = await asyncio.gather(*[_fetch_symbol_snapshot(symbol) for symbol in selected_symbols], return_exceptions=True)

    tickers: list[dict[str, Any]] = []
    unavailable: list[str] = []
    for symbol, result in zip(selected_symbols, results):
        if isinstance(result, dict) and result.get("price") is not None:
            tickers.append(result)
        else:
            unavailable.append(symbol)

    if not tickers:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sentiment": "➡️ 震荡",
            "sentiment_label": "neutral",
            "avg_change_24h": 0.0,
            "up_count": 0,
            "down_count": 0,
            "flat_count": 0,
            "tracked_count": 0,
            "requested_symbols": selected_symbols,
            "unavailable_symbols": unavailable,
            "top_gainers": [],
            "top_losers": [],
            "tickers": [],
            "sources": {},
            "error": "No market overview data available",
        }

    changes = [float(item.get("change_24h") or 0) for item in tickers]
    avg_change = round(sum(changes) / len(changes), 2)
    up_count = sum(1 for value in changes if value > 0)
    down_count = sum(1 for value in changes if value < 0)
    flat_count = len(changes) - up_count - down_count
    sentiment_label, sentiment = _classify_sentiment(avg_change)
    movers_count = min(max(int(movers), 1), min(10, len(tickers)))
    by_change_desc = sorted(tickers, key=lambda item: float(item.get("change_24h") or 0), reverse=True)
    by_change_asc = sorted(tickers, key=lambda item: float(item.get("change_24h") or 0))
    source_counts = Counter(str(item.get("exchange") or "unknown") for item in tickers)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sentiment": sentiment,
        "sentiment_label": sentiment_label,
        "avg_change_24h": avg_change,
        "up_count": up_count,
        "down_count": down_count,
        "flat_count": flat_count,
        "tracked_count": len(tickers),
        "requested_symbols": selected_symbols,
        "unavailable_symbols": unavailable,
        "top_gainers": by_change_desc[:movers_count],
        "top_losers": by_change_asc[:movers_count],
        "tickers": by_change_desc,
        "sources": dict(source_counts),
    }
