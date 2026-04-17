"""Bybit public API — free OI data (may require proxy in some regions)."""

from __future__ import annotations

from typing import Any

from app.common.http_client import fetch_json
from app.common.cache import cached

BASE = "https://api.bybit.com/v5"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


@cached(ttl=30, prefix="bybit_oi")
async def get_open_interest(
    symbol: str = "BTC",
    category: str = "linear",
) -> dict[str, Any] | None:
    """Current OI from Bybit."""
    try:
        data = await fetch_json(
            f"{BASE}/market/open-interest",
            params={
                "category": category,
                "symbol": f"{symbol.upper()}USDT",
                "intervalTime": "1h",
                "limit": 1,
            },
            headers=HEADERS,
        )
        if not isinstance(data, dict) or data.get("retCode") != 0:
            return None
        items = data.get("result", {}).get("list", [])
        if not items:
            return None
        item = items[0]
        return {
            "symbol": symbol.upper(),
            "exchange": "bybit",
            "open_interest_coin": float(item.get("openInterest", 0)),
            "timestamp": int(item.get("timestamp", 0)) // 1000,
        }
    except Exception:
        return None


@cached(ttl=60, prefix="bybit_oi_hist")
async def get_open_interest_history(
    symbol: str = "BTC",
    category: str = "linear",
    interval: str = "1h",
    limit: int = 24,
) -> list[dict[str, Any]]:
    """Historical OI from Bybit."""
    try:
        data = await fetch_json(
            f"{BASE}/market/open-interest",
            params={
                "category": category,
                "symbol": f"{symbol.upper()}USDT",
                "intervalTime": interval,
                "limit": min(limit, 200),
            },
            headers=HEADERS,
        )
        if not isinstance(data, dict) or data.get("retCode") != 0:
            return []
        items = data.get("result", {}).get("list", [])
        return [
            {
                "timestamp": int(item.get("timestamp", 0)) // 1000,
                "symbol": symbol.upper(),
                "exchange": "bybit",
                "open_interest_coin": float(item.get("openInterest", 0)),
            }
            for item in items
        ]
    except Exception:
        return []
