"""OKX public market intelligence helpers.

This module focuses on public market data and analytics endpoints that do not
require trading permissions: ticker, candles, orderbook, funding, open
interest, public indicator APIs, and OKX market filters.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.common.cache import cached
from app.common.http_client import fetch_json, fetch_json_post

BASE = "https://www.okx.com/api/v5"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

OKX_CANDLE_BARS = {
    "1m", "3m", "5m", "15m", "30m", "1H", "2H", "4H", "6H", "12H", "1D", "2D", "3D", "1W", "1M", "3M",
}
INDICATOR_BARS = {"3m", "5m", "15m", "1H", "4H", "12Hutc", "1Dutc", "3Dutc", "1Wutc"}
OI_BARS = {"5m", "15m", "1H", "4H", "1D"}

KNOWN_INDICATORS = [
    {"name": "ma", "description": "Simple Moving Average"},
    {"name": "ema", "description": "Exponential Moving Average"},
    {"name": "wma", "description": "Weighted Moving Average"},
    {"name": "dema", "description": "Double Exponential Moving Average"},
    {"name": "tema", "description": "Triple Exponential Moving Average"},
    {"name": "zlema", "description": "Zero-Lag Exponential Moving Average"},
    {"name": "hma", "description": "Hull Moving Average"},
    {"name": "kama", "description": "Kaufman Adaptive Moving Average"},
    {"name": "macd", "description": "MACD"},
    {"name": "sar", "description": "Parabolic SAR"},
    {"name": "adx", "description": "Average Directional Index"},
    {"name": "aroon", "description": "Aroon Indicator"},
    {"name": "cci", "description": "Commodity Channel Index"},
    {"name": "dpo", "description": "Detrended Price Oscillator"},
    {"name": "envelope", "description": "Envelope"},
    {"name": "halftrend", "description": "HalfTrend"},
    {"name": "alphatrend", "description": "AlphaTrend"},
    {"name": "rsi", "description": "Relative Strength Index"},
    {"name": "stoch-rsi", "description": "Stochastic RSI"},
    {"name": "stoch", "description": "Stochastic Oscillator"},
    {"name": "roc", "description": "Rate of Change"},
    {"name": "mom", "description": "Momentum"},
    {"name": "ppo", "description": "Price Percentage Oscillator"},
    {"name": "trix", "description": "TRIX"},
    {"name": "ao", "description": "Awesome Oscillator"},
    {"name": "uo", "description": "Ultimate Oscillator"},
    {"name": "wr", "description": "Williams %R"},
    {"name": "bb", "description": "Bollinger Bands"},
    {"name": "boll", "description": "Bollinger Bands (alias for bb)"},
    {"name": "bbwidth", "description": "Bollinger Band Width"},
    {"name": "bbpct", "description": "Bollinger Band %B"},
    {"name": "atr", "description": "Average True Range"},
    {"name": "keltner", "description": "Keltner Channel"},
    {"name": "donchian", "description": "Donchian Channel"},
    {"name": "hv", "description": "Historical Volatility"},
    {"name": "stddev", "description": "Standard Deviation"},
    {"name": "obv", "description": "On-Balance Volume"},
    {"name": "vwap", "description": "Volume Weighted Average Price"},
    {"name": "mvwap", "description": "Moving VWAP"},
    {"name": "cmf", "description": "Chaikin Money Flow"},
    {"name": "mfi", "description": "Money Flow Index"},
    {"name": "ad", "description": "Accumulation/Distribution"},
    {"name": "lr", "description": "Linear Regression"},
    {"name": "slope", "description": "Linear Regression Slope"},
    {"name": "angle", "description": "Linear Regression Angle"},
    {"name": "variance", "description": "Variance"},
    {"name": "meandev", "description": "Mean Deviation"},
    {"name": "sigma", "description": "Sigma"},
    {"name": "stderr", "description": "Standard Error"},
    {"name": "kdj", "description": "KDJ Stochastic Oscillator"},
    {"name": "supertrend", "description": "Supertrend"},
    {"name": "tenkan", "description": "Ichimoku Tenkan-sen"},
    {"name": "kijun", "description": "Ichimoku Kijun-sen"},
    {"name": "senkoa", "description": "Ichimoku Senkou Span A"},
    {"name": "senkob", "description": "Ichimoku Senkou Span B"},
    {"name": "chikou", "description": "Ichimoku Chikou Span"},
    {"name": "doji", "description": "Doji candlestick pattern"},
    {"name": "bull-engulf", "description": "Bullish Engulfing pattern"},
    {"name": "bear-engulf", "description": "Bearish Engulfing pattern"},
    {"name": "bull-harami", "description": "Bullish Harami pattern"},
    {"name": "bear-harami", "description": "Bearish Harami pattern"},
    {"name": "bull-harami-cross", "description": "Bullish Harami Cross pattern"},
    {"name": "bear-harami-cross", "description": "Bearish Harami Cross pattern"},
    {"name": "three-soldiers", "description": "Three White Soldiers pattern"},
    {"name": "three-crows", "description": "Three Black Crows pattern"},
    {"name": "hanging-man", "description": "Hanging Man pattern"},
    {"name": "inverted-hammer", "description": "Inverted Hammer pattern"},
    {"name": "shooting-star", "description": "Shooting Star pattern"},
    {"name": "ahr999", "description": "AHR999 Bitcoin accumulation index"},
    {"name": "rainbow", "description": "Bitcoin Rainbow Chart"},
    {"name": "fisher", "description": "Fisher Transform"},
    {"name": "nvi-pvi", "description": "Negative/Positive Volume Index"},
    {"name": "pmax", "description": "PMAX"},
    {"name": "qqe", "description": "QQE Mod"},
    {"name": "tdi", "description": "Traders Dynamic Index"},
    {"name": "waddah", "description": "Waddah Attar Explosion"},
    {"name": "range-filter", "description": "Range Filter"},
    {"name": "cho", "description": "Chande Momentum Oscillator"},
    {"name": "tr", "description": "True Range"},
    {"name": "tp", "description": "Typical Price"},
    {"name": "mp", "description": "Median Price"},
    {"name": "top-long-short", "description": "Top Trader Long/Short Ratio"},
]

INDICATOR_CODE_OVERRIDES = {
    "boll": "BB",
    "rainbow": "BTCRAINBOW",
    "stoch-rsi": "STOCHRSI",
    "bull-engulf": "BULLENGULF",
    "bear-engulf": "BEARENGULF",
    "bull-harami": "BULLHARAMI",
    "bear-harami": "BEARHARAMI",
    "bull-harami-cross": "BULLHARAMICROSS",
    "bear-harami-cross": "BEARHARAMICROSS",
    "three-soldiers": "THREESOLDIERS",
    "three-crows": "THREECROWS",
    "hanging-man": "HANGINGMAN",
    "inverted-hammer": "INVERTEDH",
    "shooting-star": "SHOOTINGSTAR",
    "nvi-pvi": "NVIPVI",
    "top-long-short": "TOPLONGSHORT",
}


def _compact(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if v is not None and v != ""}


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except Exception:
        return None


def _unwrap_rows(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict) or data.get("code") not in {"0", 0, None}:
        return []
    rows = data.get("data") or []
    return rows if isinstance(rows, list) else []


def _select_rows(rows: list[dict[str, Any]], prefer_single: bool = False) -> Any:
    if prefer_single and len(rows) <= 1:
        return rows[0] if rows else None
    return rows


def _normalize_candles(rows: list[list[Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 9:
            continue
        normalized.append({
            "timestamp": _safe_int(row[0]),
            "open": _safe_float(row[1]),
            "high": _safe_float(row[2]),
            "low": _safe_float(row[3]),
            "close": _safe_float(row[4]),
            "volume": _safe_float(row[5]),
            "volume_ccy": _safe_float(row[6]),
            "volume_quote": _safe_float(row[7]),
            "confirmed": str(row[8]) == "1",
        })
    return normalized


def _normalize_orderbook(row: dict[str, Any], inst_id: str, depth: int) -> dict[str, Any]:
    bids = row.get("bids") or []
    asks = row.get("asks") or []
    norm_bids = [
        {"price": _safe_float(level[0]), "size": _safe_float(level[1])}
        for level in bids[:depth]
        if isinstance(level, list)
        and len(level) >= 2
        and (_safe_float(level[0]) or 0) > 0
        and (_safe_float(level[1]) or 0) > 0
    ]
    norm_asks = [
        {"price": _safe_float(level[0]), "size": _safe_float(level[1])}
        for level in asks[:depth]
        if isinstance(level, list)
        and len(level) >= 2
        and (_safe_float(level[0]) or 0) > 0
        and (_safe_float(level[1]) or 0) > 0
    ]
    best_bid = norm_bids[0]["price"] if norm_bids else None
    best_ask = norm_asks[0]["price"] if norm_asks else None
    spread = (best_ask - best_bid) if best_bid is not None and best_ask is not None else None
    bid_notional = sum((level["price"] or 0) * (level["size"] or 0) for level in norm_bids[:5])
    ask_notional = sum((level["price"] or 0) * (level["size"] or 0) for level in norm_asks[:5])
    total_notional = bid_notional + ask_notional
    imbalance = ((bid_notional - ask_notional) / total_notional) if total_notional else None
    return {
        "instId": inst_id,
        "timestamp": _safe_int(row.get("ts")),
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": spread,
        "bid_depth_notional_top5": bid_notional,
        "ask_depth_notional_top5": ask_notional,
        "imbalance_top5": imbalance,
        "bids": norm_bids,
        "asks": norm_asks,
    }


def _infer_inst_type(inst_id: str) -> str:
    upper = inst_id.upper()
    if upper.endswith("-SWAP"):
        return "SWAP"
    if upper.count("-") >= 3 and upper.endswith(("-C", "-P")):
        return "OPTION"
    parts = upper.split("-")
    if len(parts) >= 3 and parts[1] in {"USD", "USDT", "USDC"} and parts[2].isdigit():
        return "FUTURES"
    return "SPOT"


def _extract_base_symbol(inst_id: str) -> str:
    return inst_id.split("-")[0].upper()


def _resolve_indicator_code(indicator: str) -> str:
    key = indicator.strip().lower()
    return INDICATOR_CODE_OVERRIDES.get(key, key.upper().replace("-", "_"))


def _extract_indicator_latest(
    payload: dict[str, Any] | None,
    indicator: str,
    timeframe: str,
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    outer_rows = payload.get("data")
    if not isinstance(outer_rows, list) or not outer_rows:
        return None
    outer_row = outer_rows[0]
    if not isinstance(outer_row, dict):
        return None
    inner_rows = outer_row.get("data")
    if not isinstance(inner_rows, list) or not inner_rows:
        return None
    inst_row = inner_rows[0]
    if not isinstance(inst_row, dict):
        return None
    timeframes = inst_row.get("timeframes")
    if not isinstance(timeframes, dict):
        return None
    tf_row = timeframes.get(timeframe)
    if not isinstance(tf_row, dict):
        return None
    indicators = tf_row.get("indicators")
    if not isinstance(indicators, dict):
        return None

    indicator_code = _resolve_indicator_code(indicator)
    series = indicators.get(indicator_code)
    if not isinstance(series, list) or not series:
        return None
    latest = series[0]
    if not isinstance(latest, dict):
        return None
    values = latest.get("values")
    if not isinstance(values, dict):
        return None
    return {
        "ts": _safe_int(latest.get("ts")),
        "values": values,
    }


async def _public_get(path: str, params: dict[str, Any] | None = None) -> Any:
    return await fetch_json(f"{BASE}{path}", params=params, headers=HEADERS)


async def _public_post(path: str, body: dict[str, Any]) -> Any:
    return await fetch_json_post(f"{BASE}{path}", json_body=body, headers=HEADERS)


@cached(ttl=10, prefix="okx_ticker")
async def get_ticker(inst_id: str) -> dict[str, Any] | None:
    rows = _unwrap_rows(await _public_get("/market/ticker", {"instId": inst_id}))
    return rows[0] if rows else None


@cached(ttl=10, prefix="okx_tickers")
async def get_tickers(inst_type: str, uly: str | None = None, inst_family: str | None = None) -> list[dict[str, Any]]:
    rows = _unwrap_rows(await _public_get(
        "/market/tickers",
        _compact({"instType": inst_type.upper(), "uly": uly, "instFamily": inst_family}),
    ))
    return rows


@cached(ttl=10, prefix="okx_index_ticker")
async def get_index_ticker(
    inst_id: str | None = None,
    quote_ccy: str | None = None,
) -> list[dict[str, Any]]:
    rows = _unwrap_rows(await _public_get(
        "/market/index-tickers",
        _compact({"instId": inst_id, "quoteCcy": quote_ccy}),
    ))
    return rows


@cached(ttl=10, prefix="okx_orderbook")
async def get_orderbook(inst_id: str, sz: int = 20) -> dict[str, Any] | None:
    rows = _unwrap_rows(await _public_get("/market/books", {"instId": inst_id, "sz": min(max(sz, 1), 400)}))
    if not rows:
        return None
    return _normalize_orderbook(rows[0], inst_id, min(max(sz, 1), 400))


def _normalize_trade_rows(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        price = _safe_float(row.get("px"))
        size = _safe_float(row.get("sz"))
        if price is None or price <= 0 or size is None or size <= 0:
            continue
        item = dict(row)
        item["px"] = price
        item["sz"] = size
        item["ts"] = _safe_int(row.get("ts"))
        normalized.append(item)
        if len(normalized) >= limit:
            break
    return normalized


@cached(ttl=30, prefix="okx_candles")
async def get_candles(
    inst_id: str,
    bar: str = "1H",
    after: str | None = None,
    before: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    resolved_bar = bar if bar in OKX_CANDLE_BARS else "1H"
    query = _compact({
        "instId": inst_id,
        "bar": resolved_bar,
        "after": after,
        "before": before,
        "limit": min(max(limit, 1), 300),
    })
    use_history = bool(after) and (_safe_int(after) or 0) < int(time.time() * 1000) - 2 * 24 * 60 * 60 * 1000
    path = "/market/history-candles" if use_history else "/market/candles"
    data = await _public_get(path, query)
    rows = data.get("data") if isinstance(data, dict) else []
    normalized = _normalize_candles(rows if isinstance(rows, list) else [])
    if normalized or use_history or not (after or before):
        return normalized
    fallback = await _public_get("/market/history-candles", query)
    rows = fallback.get("data") if isinstance(fallback, dict) else []
    return _normalize_candles(rows if isinstance(rows, list) else [])


@cached(ttl=30, prefix="okx_index_candles")
async def get_index_candles(
    inst_id: str,
    bar: str = "1m",
    after: str | None = None,
    before: str | None = None,
    limit: int = 100,
    history: bool = False,
) -> list[dict[str, Any]]:
    resolved_bar = bar if bar in OKX_CANDLE_BARS else "1m"
    query = _compact({
        "instId": inst_id,
        "bar": resolved_bar,
        "after": after,
        "before": before,
        "limit": min(max(limit, 1), 300),
    })
    path = "/market/history-index-candles" if history else "/market/index-candles"
    data = await _public_get(path, query)
    rows = data.get("data") if isinstance(data, dict) else []
    normalized = _normalize_candles(rows if isinstance(rows, list) else [])
    if normalized or history or not (after or before):
        return normalized
    fallback = await _public_get("/market/history-index-candles", query)
    rows = fallback.get("data") if isinstance(fallback, dict) else []
    return _normalize_candles(rows if isinstance(rows, list) else [])


@cached(ttl=300, prefix="okx_instruments")
async def get_instruments(
    inst_type: str,
    inst_id: str | None = None,
    uly: str | None = None,
    inst_family: str | None = None,
) -> Any:
    rows = _unwrap_rows(await _public_get(
        "/public/instruments",
        _compact({
            "instType": inst_type.upper(),
            "instId": inst_id,
            "uly": uly,
            "instFamily": inst_family,
        }),
    ))
    return _select_rows(rows, prefer_single=bool(inst_id))


@cached(ttl=120, prefix="okx_funding")
async def get_funding_rate(
    inst_id: str,
    *,
    history: bool = False,
    after: str | None = None,
    before: str | None = None,
    limit: int = 20,
) -> Any:
    path = "/public/funding-rate-history" if history else "/public/funding-rate"
    query = {"instId": inst_id} if not history else _compact({
        "instId": inst_id,
        "after": after,
        "before": before,
        "limit": min(max(limit, 1), 100),
    })
    rows = _unwrap_rows(await _public_get(path, query))
    return _select_rows(rows, prefer_single=not history)


@cached(ttl=120, prefix="okx_mark_price")
async def get_mark_price(
    inst_type: str,
    inst_id: str | None = None,
    uly: str | None = None,
    inst_family: str | None = None,
) -> Any:
    rows = _unwrap_rows(await _public_get(
        "/public/mark-price",
        _compact({
            "instType": inst_type.upper(),
            "instId": inst_id,
            "uly": uly,
            "instFamily": inst_family,
        }),
    ))
    return _select_rows(rows, prefer_single=bool(inst_id))


@cached(ttl=10, prefix="okx_trades")
async def get_trades(inst_id: str, limit: int = 20) -> list[dict[str, Any]]:
    rows = _unwrap_rows(await _public_get("/market/trades", {"instId": inst_id, "limit": min(max(limit, 1), 500)}))
    return _normalize_trade_rows(rows, min(max(limit, 1), 500))


@cached(ttl=120, prefix="okx_price_limit")
async def get_price_limit(inst_id: str) -> dict[str, Any] | None:
    rows = _unwrap_rows(await _public_get("/public/price-limit", {"instId": inst_id}))
    return rows[0] if rows else None


@cached(ttl=120, prefix="okx_open_interest")
async def get_public_open_interest(
    inst_type: str = "SWAP",
    inst_id: str | None = None,
    uly: str | None = None,
    inst_family: str | None = None,
) -> Any:
    rows = _unwrap_rows(await _public_get(
        "/public/open-interest",
        _compact({
            "instType": inst_type.upper(),
            "instId": inst_id,
            "uly": uly,
            "instFamily": inst_family,
        }),
    ))
    return _select_rows(rows, prefer_single=bool(inst_id))


@cached(ttl=600, prefix="okx_stock_tokens")
async def get_stock_tokens(inst_type: str = "SWAP", inst_id: str | None = None) -> list[dict[str, Any]]:
    instruments = await get_instruments(inst_type=inst_type, inst_id=inst_id)
    rows = instruments if isinstance(instruments, list) else ([instruments] if isinstance(instruments, dict) else [])
    return [row for row in rows if row.get("instCategory") == "3"]


@cached(ttl=600, prefix="okx_inst_category")
async def get_instruments_by_category(
    inst_category: str,
    inst_type: str = "SWAP",
    inst_id: str | None = None,
) -> list[dict[str, Any]]:
    instruments = await get_instruments(inst_type=inst_type, inst_id=inst_id)
    rows = instruments if isinstance(instruments, list) else ([instruments] if isinstance(instruments, dict) else [])
    return [row for row in rows if row.get("instCategory") == str(inst_category)]


@cached(ttl=300, prefix="okx_indicator")
async def get_indicator(
    inst_id: str,
    indicator: str,
    *,
    bar: str = "1H",
    params: list[float] | None = None,
    return_list: bool = False,
    limit: int = 10,
    backtest_time: int | None = None,
) -> dict[str, Any]:
    resolved_bar = bar if bar in INDICATOR_BARS else "1H"
    body = _compact({
        "instId": inst_id,
        "timeframes": [resolved_bar],
        "indicators": {
            _resolve_indicator_code(indicator): _compact({
                "paramList": params or None,
                "returnList": return_list,
                "limit": min(max(limit, 1), 100) if return_list else None,
            })
        },
        "backtestTime": backtest_time,
    })
    data = await _public_post("/aigc/mcp/indicators", body)
    return data if isinstance(data, dict) else {"data": data}


async def list_indicators() -> list[dict[str, str]]:
    return KNOWN_INDICATORS


@cached(ttl=300, prefix="okx_market_filter")
async def market_filter(
    inst_type: str,
    *,
    base_ccy: str | None = None,
    quote_ccy: str | None = None,
    settle_ccy: str | None = None,
    inst_family: str | None = None,
    ct_type: str | None = None,
    min_last: str | None = None,
    max_last: str | None = None,
    min_chg24h_pct: str | None = None,
    max_chg24h_pct: str | None = None,
    min_market_cap_usd: str | None = None,
    max_market_cap_usd: str | None = None,
    min_vol_usd_24h: str | None = None,
    max_vol_usd_24h: str | None = None,
    min_funding_rate: str | None = None,
    max_funding_rate: str | None = None,
    min_oi_usd: str | None = None,
    max_oi_usd: str | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    body = _compact({
        "instType": inst_type.upper(),
        "baseCcy": base_ccy,
        "quoteCcy": quote_ccy,
        "settleCcy": settle_ccy,
        "instFamily": inst_family,
        "ctType": ct_type,
        "minLast": min_last,
        "maxLast": max_last,
        "minChg24hPct": min_chg24h_pct,
        "maxChg24hPct": max_chg24h_pct,
        "minMarketCapUsd": min_market_cap_usd,
        "maxMarketCapUsd": max_market_cap_usd,
        "minVolUsd24h": min_vol_usd_24h,
        "maxVolUsd24h": max_vol_usd_24h,
        "minFundingRate": min_funding_rate,
        "maxFundingRate": max_funding_rate,
        "minOiUsd": min_oi_usd,
        "maxOiUsd": max_oi_usd,
        "sortBy": sort_by,
        "sortOrder": sort_order,
        "limit": min(max(limit, 1), 100),
    })
    try:
        data = await _public_post("/aigc/mcp/market-filter", body)
    except Exception:
        return []
    if isinstance(data, dict):
        rows = data.get("data")
        return rows if isinstance(rows, list) else []
    return []


def _normalize_legacy_oi_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    resolved_oi = [_safe_float(row.get("open_interest_usd")) for row in rows]
    for idx, row in enumerate(rows):
        ts = _safe_int(row.get("timestamp"))
        oi_usd = resolved_oi[idx]
        volume_usd = _safe_float(row.get("volume_usd"))
        mapped = {
            "ts": ts * 1000 if ts is not None and ts < 10**12 else ts,
            "oiUsd": oi_usd,
            "volUsd24h": volume_usd,
            "oiDeltaUsd": None,
            "oiDeltaPct": None,
        }
        next_oi = resolved_oi[idx + 1] if idx + 1 < len(resolved_oi) else None
        if oi_usd is not None and next_oi not in {None, 0}:
            delta_usd = oi_usd - next_oi
            mapped["oiDeltaUsd"] = delta_usd
            mapped["oiDeltaPct"] = (delta_usd / next_oi) * 100
        normalized.append(mapped)
    return normalized


@cached(ttl=120, prefix="okx_oi_history")
async def get_oi_history(
    inst_id: str,
    *,
    bar: str = "1H",
    limit: int = 50,
    ts: int | None = None,
) -> list[dict[str, Any]]:
    resolved_bar = bar if bar in OI_BARS else "1H"
    body = _compact({
        "instId": inst_id,
        "bar": resolved_bar,
        "limit": min(max(limit, 1), 500),
        "ts": ts,
    })
    try:
        data = await _public_post("/aigc/mcp/oi-history", body)
        if isinstance(data, dict):
            rows = data.get("data")
            if isinstance(rows, list) and rows:
                return rows
    except Exception:
        pass

    legacy_rows = await get_open_interest_history(_extract_base_symbol(inst_id), period=resolved_bar, limit=limit)
    return _normalize_legacy_oi_rows(legacy_rows)


@cached(ttl=120, prefix="okx_oi_change")
async def filter_oi_change(
    inst_type: str = "SWAP",
    *,
    bar: str = "1H",
    min_oi_usd: str | None = None,
    min_vol_usd_24h: str | None = None,
    min_abs_oi_delta_pct: str | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    resolved_bar = bar if bar in OI_BARS else "1H"
    body = _compact({
        "instType": inst_type.upper(),
        "bar": resolved_bar,
        "minOiUsd": min_oi_usd,
        "minVolUsd24h": min_vol_usd_24h,
        "minAbsOiDeltaPct": min_abs_oi_delta_pct,
        "sortBy": sort_by,
        "sortOrder": sort_order,
        "limit": min(max(limit, 1), 100),
    })
    try:
        data = await _public_post("/aigc/mcp/oi-change-filter", body)
    except Exception:
        return []
    if isinstance(data, dict):
        rows = data.get("data")
        return rows if isinstance(rows, list) else []
    return []


@cached(ttl=60, prefix="okx_intelligence")
async def build_market_intelligence(
    inst_id: str,
    *,
    candle_bar: str = "1H",
    orderbook_depth: int = 20,
    trade_limit: int = 20,
    oi_bar: str = "1H",
    oi_limit: int = 30,
) -> dict[str, Any]:
    inst_type = _infer_inst_type(inst_id)
    base_symbol = _extract_base_symbol(inst_id)
    include_funding = inst_type == "SWAP"
    include_mark_price = inst_type in {"SWAP", "FUTURES", "OPTION"}
    include_oi = inst_type in {"SWAP", "FUTURES", "OPTION"}
    include_price_limit = inst_type in {"SWAP", "FUTURES"}

    ticker_task = get_ticker(inst_id)
    orderbook_task = get_orderbook(inst_id, sz=orderbook_depth)
    candles_task = get_candles(inst_id, bar=candle_bar, limit=120)
    trades_task = get_trades(inst_id, limit=trade_limit)
    instruments_task = get_instruments(inst_type, inst_id=inst_id)
    funding_task = get_funding_rate(inst_id) if include_funding else asyncio.sleep(0, result=None)
    mark_price_task = get_mark_price(inst_type, inst_id=inst_id) if include_mark_price else asyncio.sleep(0, result=None)
    open_interest_task = get_public_open_interest(inst_type, inst_id=inst_id) if include_oi else asyncio.sleep(0, result=None)
    price_limit_task = get_price_limit(inst_id) if include_price_limit else asyncio.sleep(0, result=None)
    oi_history_task = get_oi_history(inst_id, bar=oi_bar, limit=oi_limit) if include_price_limit else asyncio.sleep(0, result=[])
    indicators_task = asyncio.gather(
        get_indicator(inst_id, "rsi", bar=candle_bar),
        get_indicator(inst_id, "macd", bar=candle_bar),
        get_indicator(inst_id, "bb", bar=candle_bar),
        return_exceptions=True,
    )

    ticker, orderbook, candles, trades, instrument, funding, mark_price, open_interest, price_limit, oi_history, indicators = await asyncio.gather(
        ticker_task,
        orderbook_task,
        candles_task,
        trades_task,
        instruments_task,
        funding_task,
        mark_price_task,
        open_interest_task,
        price_limit_task,
        oi_history_task,
        indicators_task,
    )

    last_price = _safe_float((ticker or {}).get("last"))
    open_24h = _safe_float((ticker or {}).get("open24h"))
    price_change_pct = None
    if last_price is not None and open_24h not in {None, 0}:
        price_change_pct = (last_price - open_24h) / open_24h * 100

    oi_row = open_interest if isinstance(open_interest, dict) else ((open_interest or [None])[0] if isinstance(open_interest, list) else None)
    oi_usd = _safe_float((oi_row or {}).get("oiUsd"))
    oi_history_rows = oi_history if isinstance(oi_history, list) else []
    oi_delta_pct = None
    oi_delta_usd = None
    if len(oi_history_rows) >= 2:
        latest = oi_history_rows[0] or {}
        previous = oi_history_rows[1] or {}
        oi_delta_pct = _safe_float(latest.get("oiDeltaPct"))
        oi_delta_usd = _safe_float(latest.get("oiDeltaUsd"))
        if oi_delta_pct is None:
            latest_oi = _safe_float(latest.get("oiUsd"))
            previous_oi = _safe_float(previous.get("oiUsd"))
            if latest_oi is not None and previous_oi not in {None, 0}:
                oi_delta_usd = latest_oi - previous_oi
                oi_delta_pct = (oi_delta_usd / previous_oi) * 100

    orderbook_bias = None
    imbalance = _safe_float((orderbook or {}).get("imbalance_top5")) if isinstance(orderbook, dict) else None
    if imbalance is not None:
        if imbalance >= 0.08:
            orderbook_bias = "bid_support"
        elif imbalance <= -0.08:
            orderbook_bias = "ask_pressure"
        else:
            orderbook_bias = "balanced"

    regime = "neutral"
    if price_change_pct is not None and oi_delta_pct is not None:
        if price_change_pct > 0 and oi_delta_pct > 0:
            regime = "price_up_oi_up"
        elif price_change_pct > 0 and oi_delta_pct < 0:
            regime = "price_up_oi_down"
        elif price_change_pct < 0 and oi_delta_pct > 0:
            regime = "price_down_oi_up"
        elif price_change_pct < 0 and oi_delta_pct < 0:
            regime = "price_down_oi_down"

    diagnosis_map = {
        "price_up_oi_up": "上涨同时伴随持仓增加，偏趋势延续或杠杆多头继续入场。",
        "price_up_oi_down": "上涨但持仓下降，更像空头回补或挤空后的去杠杆。",
        "price_down_oi_up": "下跌同时持仓增加，偏新空头建立或下行趋势确认。",
        "price_down_oi_down": "下跌且持仓下降，更像多头止损 / 强平后的去杠杆。",
        "neutral": "当前价格与持仓变化没有形成明确共振，更多依赖盘口和指标确认。",
    }

    funding_rate = _safe_float((funding or {}).get("fundingRate")) if isinstance(funding, dict) else None
    funding_bias = None
    if funding_rate is not None:
        if funding_rate >= 0.0005:
            funding_bias = "crowded_longs"
        elif funding_rate <= -0.0005:
            funding_bias = "crowded_shorts"
        else:
            funding_bias = "neutral"

    indicator_payload = {}
    for name, item in zip(("rsi", "macd", "bb"), indicators):
        if isinstance(item, Exception):
            indicator_payload[name] = {"error": str(item)}
        else:
            indicator_payload[name] = item

    indicator_summary = {
        "rsi": _extract_indicator_latest(indicator_payload.get("rsi"), "rsi", candle_bar),
        "macd": _extract_indicator_latest(indicator_payload.get("macd"), "macd", candle_bar),
        "bb": _extract_indicator_latest(indicator_payload.get("bb"), "bb", candle_bar),
    }

    return {
        "instId": inst_id,
        "instType": inst_type,
        "baseSymbol": base_symbol,
        "snapshot": {
            "last": last_price,
            "open24h": open_24h,
            "high24h": _safe_float((ticker or {}).get("high24h")) if isinstance(ticker, dict) else None,
            "low24h": _safe_float((ticker or {}).get("low24h")) if isinstance(ticker, dict) else None,
            "price_change_pct_24h": price_change_pct,
            "volume_24h_base": _safe_float((ticker or {}).get("vol24h")) if isinstance(ticker, dict) else None,
            "volume_24h_quote": _safe_float((ticker or {}).get("volCcy24h")) if isinstance(ticker, dict) else None,
            "mark_price": _safe_float((mark_price or {}).get("markPx")) if isinstance(mark_price, dict) else None,
            "funding_rate": funding_rate,
            "oi_usd": oi_usd,
            "oi_delta_usd": oi_delta_usd,
            "oi_delta_pct": oi_delta_pct,
        },
        "diagnosis": {
            "price_oi_regime": regime,
            "price_oi_comment": diagnosis_map[regime],
            "orderbook_bias": orderbook_bias,
            "funding_bias": funding_bias,
        },
        "ticker": ticker,
        "instrument": instrument,
        "orderbook": orderbook,
        "candles": candles,
        "recent_trades": trades,
        "funding": funding,
        "mark_price": mark_price,
        "price_limit": price_limit,
        "open_interest": open_interest,
        "oi_history": oi_history_rows,
        "indicators": indicator_payload,
        "indicator_summary": indicator_summary,
    }


@cached(ttl=60, prefix="okx_oi")
async def get_open_interest_history(
    symbol: str = "BTC",
    period: str = "1H",
    limit: int = 48,
) -> list[dict[str, Any]]:
    """Legacy helper kept for the current OI pages.

    Returns [timestamp, oi_usd, volume_usd] tuples from the Rubik endpoint.
    """
    try:
        data = await _public_get(
            "/rubik/stat/contracts/open-interest-volume",
            {"ccy": symbol.upper(), "period": period},
        )
        if not isinstance(data, dict) or data.get("code") != "0":
            return []
        rows = data.get("data") or []
        results: list[dict[str, Any]] = []
        for row in rows[:limit]:
            if not isinstance(row, list) or len(row) < 3:
                continue
            results.append({
                "timestamp": int(row[0]) // 1000,
                "symbol": symbol.upper(),
                "exchange": "okx",
                "open_interest_usd": float(row[1]),
                "volume_usd": float(row[2]),
            })
        return results
    except Exception:
        return []


@cached(ttl=30, prefix="okx_oi_cur")
async def get_open_interest(symbol: str = "BTC") -> dict[str, Any] | None:
    """Legacy current OI snapshot used by existing pages."""
    history = await get_open_interest_history(symbol, period="1H", limit=1)
    if not history:
        return None
    latest = history[0]
    return {
        "symbol": symbol.upper(),
        "exchange": "okx",
        "open_interest_usd": latest["open_interest_usd"],
        "volume_usd": latest.get("volume_usd"),
    }


@cached(ttl=60, prefix="okx_ls")
async def get_long_short_ratio(
    symbol: str = "BTC",
    period: str = "1H",
    limit: int = 48,
) -> list[dict[str, Any]]:
    """Long/short account ratio from OKX Rubik."""
    try:
        data = await _public_get(
            "/rubik/stat/contracts/long-short-account-ratio",
            {"ccy": symbol.upper(), "period": period},
        )
        if not isinstance(data, dict) or data.get("code") != "0":
            return []
        rows = data.get("data") or []
        results: list[dict[str, Any]] = []
        for row in rows[:limit]:
            if not isinstance(row, list) or len(row) < 2:
                continue
            results.append({
                "timestamp": int(row[0]) // 1000,
                "symbol": symbol.upper(),
                "exchange": "okx",
                "long_short_ratio": float(row[1]),
            })
        return results
    except Exception:
        return []
