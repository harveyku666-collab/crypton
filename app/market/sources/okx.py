"""OKX public API — OI and derivatives data (may require proxy in some regions)."""

from __future__ import annotations

from typing import Any

from app.common.http_client import fetch_json
from app.common.cache import cached

BASE = "https://www.okx.com/api/v5"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


@cached(ttl=60, prefix="okx_oi")
async def get_open_interest_history(
    symbol: str = "BTC",
    period: str = "1H",
    limit: int = 48,
) -> list[dict[str, Any]]:
    """OI + volume history from OKX Rubik API.
    Returns [timestamp, oi_usd, volume_usd] tuples.
    """
    try:
        data = await fetch_json(
            f"{BASE}/rubik/stat/contracts/open-interest-volume",
            params={"ccy": symbol.upper(), "period": period},
            headers=HEADERS,
        )
        if not isinstance(data, dict) or data.get("code") != "0":
            return []
        rows = data.get("data", [])
        results = []
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
    """Current OI snapshot from OKX (derived from history endpoint, first entry)."""
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
    """Long/short account ratio from OKX."""
    try:
        data = await fetch_json(
            f"{BASE}/rubik/stat/contracts/long-short-account-ratio",
            params={"ccy": symbol.upper(), "period": period},
            headers=HEADERS,
        )
        if not isinstance(data, dict) or data.get("code") != "0":
            return []
        rows = data.get("data", [])
        results = []
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
