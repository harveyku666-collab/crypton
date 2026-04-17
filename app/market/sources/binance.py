"""Binance public API — ported from crypto-funding-alert + btc-quant-predictor."""

from __future__ import annotations

from typing import Any

from app.common.http_client import fetch_json
from app.common.cache import cached

BASES = [
    "https://api.binance.com",
    "https://api-gcp.binance.com",
    "https://data-api.binance.vision",
]
FAPI = "https://fapi.binance.com"
HEADERS = {"User-Agent": "Mozilla/5.0"}

FUNDING_SYMBOLS = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "DOT", "LINK",
    "MATIC", "UNI", "ATOM", "LTC", "FIL", "APT", "ARB", "OP", "NEAR", "SUI",
    "TIA", "SEI", "INJ", "FET", "RNDR", "WLD", "PEPE", "SHIB", "BONK", "WIF",
    "AAVE", "MKR", "CRV", "SNX", "COMP", "LDO", "EIGEN", "JUP", "JTO", "PYTH",
]


async def _try_bases(path: str, params: dict | None = None) -> Any:
    for base in BASES:
        try:
            return await fetch_json(f"{base}{path}", params=params, headers=HEADERS)
        except Exception:
            continue
    return None


@cached(ttl=10, prefix="binance")
async def get_klines(symbol: str = "BTCUSDT", interval: str = "15m", limit: int = 50) -> list[list]:
    data = await _try_bases("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit})
    return data if isinstance(data, list) else []


@cached(ttl=10, prefix="binance")
async def get_ticker_24h(symbol: str = "BTCUSDT") -> dict[str, Any] | None:
    data = await _try_bases("/api/v3/ticker/24hr", {"symbol": symbol})
    return data if isinstance(data, dict) else None


@cached(ttl=300, prefix="binance")
async def get_funding_rate(symbol: str) -> dict[str, Any] | None:
    """Get current funding rate from Binance Futures."""
    try:
        data = await fetch_json(f"{FAPI}/fapi/v1/premiumIndex", params={"symbol": f"{symbol}USDT"})
        return data if isinstance(data, dict) else None
    except Exception:
        return None


@cached(ttl=300, prefix="binance")
async def get_futures_ticker(symbol: str) -> dict[str, Any] | None:
    try:
        data = await fetch_json(f"{FAPI}/fapi/v1/ticker/24hr", params={"symbol": f"{symbol}USDT"})
        return data if isinstance(data, dict) else None
    except Exception:
        return None


@cached(ttl=10, prefix="binance")
async def get_order_book(symbol: str = "BTCUSDT", limit: int = 20) -> dict[str, Any] | None:
    """Order book depth from Binance (free, no key needed)."""
    data = await _try_bases("/api/v3/depth", {"symbol": symbol, "limit": min(limit, 5000)})
    if not isinstance(data, dict):
        return None
    return {
        "symbol": symbol,
        "bids": [{"price": float(b[0]), "qty": float(b[1])} for b in (data.get("bids") or [])[:limit]],
        "asks": [{"price": float(a[0]), "qty": float(a[1])} for a in (data.get("asks") or [])[:limit]],
        "source": "binance",
    }


@cached(ttl=60, prefix="binance")
async def get_long_short_ratio(symbol: str = "BTCUSDT", period: str = "1h", limit: int = 24) -> list[dict[str, Any]]:
    """Top trader long/short ratio from Binance Futures (free)."""
    try:
        data = await fetch_json(
            f"{FAPI}/futures/data/topLongShortAccountRatio",
            params={"symbol": symbol, "period": period, "limit": min(limit, 500)},
        )
        if not isinstance(data, list):
            return []
        return [
            {
                "symbol": symbol.replace("USDT", ""),
                "timestamp": item.get("timestamp"),
                "long_account": float(item.get("longAccount", 0)),
                "short_account": float(item.get("shortAccount", 0)),
                "long_short_ratio": float(item.get("longShortRatio", 0)),
                "source": "binance",
            }
            for item in data
        ]
    except Exception:
        return []


@cached(ttl=30, prefix="binance_oi")
async def get_open_interest(symbol: str = "BTCUSDT") -> dict[str, Any] | None:
    """Open interest from Binance Futures (requires proxy in restricted regions)."""
    try:
        data = await fetch_json(f"{FAPI}/fapi/v1/openInterest", params={"symbol": symbol})
        if not isinstance(data, dict) or "openInterest" not in data:
            return None
        ticker = await get_futures_ticker(symbol.replace("USDT", ""))
        mark_price = float(ticker.get("lastPrice", 0)) if ticker else 0
        oi_coin = float(data["openInterest"])
        return {
            "symbol": symbol.replace("USDT", ""),
            "exchange": "binance",
            "open_interest_coin": oi_coin,
            "open_interest_usd": round(oi_coin * mark_price, 2) if mark_price else None,
            "mark_price": mark_price or None,
            "timestamp": data.get("time"),
        }
    except Exception:
        return None


@cached(ttl=60, prefix="binance_oi_hist")
async def get_open_interest_history(
    symbol: str = "BTCUSDT", period: str = "5m", limit: int = 30,
) -> list[dict[str, Any]]:
    """Historical OI from Binance Futures (requires proxy in restricted regions)."""
    try:
        data = await fetch_json(
            f"{FAPI}/futures/data/openInterestHist",
            params={"symbol": symbol, "period": period, "limit": min(limit, 500)},
        )
        if not isinstance(data, list):
            return []
        return [
            {
                "symbol": symbol.replace("USDT", ""),
                "exchange": "binance",
                "timestamp": item.get("timestamp"),
                "open_interest_coin": float(item.get("sumOpenInterest", 0)),
                "open_interest_usd": float(item.get("sumOpenInterestValue", 0)),
            }
            for item in data
        ]
    except Exception:
        return []


async def scan_funding_rates(min_abs_rate: float = 0.0005, min_volume: float = 10_000_000) -> list[dict]:
    """Scan all tracked symbols for funding rate opportunities."""
    import asyncio

    async def _check(sym: str) -> dict | None:
        fund = await get_funding_rate(sym)
        tick = await get_futures_ticker(sym)
        if not fund or not tick:
            return None
        rate = float(fund.get("lastFundingRate", 0))
        volume = float(tick.get("quoteVolume", 0))
        price_change = float(tick.get("priceChangePercent", 0))
        last_price = float(tick.get("lastPrice", 0))
        if abs(rate) < min_abs_rate or volume < min_volume:
            return None
        annual_rate = abs(rate) * 3 * 365 * 100
        score = abs(rate) * 10000 * 0.4 + (volume / 1e9) * 0.3 + (price_change if rate < 0 else -price_change) * 0.3
        signal = "STRONG" if score > 50 else "MODERATE" if score > 25 else "WATCH"
        return {
            "symbol": sym,
            "rate": rate,
            "rate_pct": rate * 100,
            "price": last_price,
            "price_change_pct": price_change,
            "volume_24h": volume,
            "annual_rate_3x": annual_rate,
            "score": round(score, 1),
            "signal": signal,
            "direction": "LONG" if rate < 0 else "SHORT",
        }

    results = await asyncio.gather(*[_check(s) for s in FUNDING_SYMBOLS], return_exceptions=True)
    valid = [r for r in results if isinstance(r, dict)]
    valid.sort(key=lambda x: x["score"], reverse=True)
    return valid
