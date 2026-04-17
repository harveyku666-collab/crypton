"""Bitget public Futures API — free, no API key required."""

from __future__ import annotations

from typing import Any

from app.common.http_client import fetch_json
from app.common.cache import cached

BASE = "https://api.bitget.com/api/v2"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


@cached(ttl=30, prefix="bitget_oi")
async def get_open_interest(symbol: str = "BTC", product_type: str = "USDT-FUTURES") -> dict[str, Any] | None:
    """Current open interest from Bitget (coin-denominated size)."""
    try:
        data = await fetch_json(
            f"{BASE}/mix/market/open-interest",
            params={"productType": product_type, "symbol": f"{symbol.upper()}USDT"},
            headers=HEADERS,
        )
        if not isinstance(data, dict) or data.get("code") != "00000":
            return None
        items = data.get("data", {}).get("openInterestList", [])
        if not items:
            return None
        item = items[0]
        return {
            "symbol": symbol.upper(),
            "exchange": "bitget",
            "open_interest_coin": float(item.get("size", 0)),
        }
    except Exception:
        return None
