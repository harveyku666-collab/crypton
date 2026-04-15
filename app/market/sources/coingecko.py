"""CoinGecko data source — ported from crypto-tracker-cn."""

from __future__ import annotations

from typing import Any

from app.common.http_client import fetch_json
from app.common.cache import cached

BASE = "https://api.coingecko.com/api/v3"
FNG_URL = "https://api.alternative.me/fng"


@cached(ttl=30, prefix="gecko")
async def get_prices(ids: str = "bitcoin,ethereum,solana") -> dict[str, Any]:
    return await fetch_json(
        f"{BASE}/simple/price",
        params={
            "ids": ids,
            "vs_currencies": "usd",
            "include_24hr_change": "true",
            "include_market_cap": "true",
        },
    )


@cached(ttl=60, prefix="gecko")
async def get_global() -> dict[str, Any]:
    data = await fetch_json(f"{BASE}/global")
    return data.get("data", {})


@cached(ttl=60, prefix="gecko")
async def get_trending() -> list[dict]:
    data = await fetch_json(f"{BASE}/search/trending")
    results = []
    for c in data.get("coins", []):
        item = c.get("item", {})
        coin_data = item.get("data", {})
        entry = {
            "id": item.get("id"),
            "name": item.get("name"),
            "symbol": item.get("symbol"),
            "market_cap_rank": item.get("market_cap_rank"),
            "price_btc": item.get("price_btc"),
            "score": item.get("score"),
        }
        if coin_data:
            entry["price_usd"] = coin_data.get("price")
            entry["price_change_24h"] = coin_data.get("price_change_percentage_24h", {}).get("usd")
            entry["market_cap"] = coin_data.get("market_cap")
            entry["total_volume"] = coin_data.get("total_volume")
        results.append(entry)
    return results


@cached(ttl=120, prefix="gecko")
async def get_fear_greed() -> dict[str, Any] | None:
    data = await fetch_json(FNG_URL)
    entries = data.get("data", [])
    return entries[0] if entries else None


@cached(ttl=60, prefix="gecko")
async def get_meme_coins(limit: int = 15) -> list[dict]:
    return await fetch_json(
        f"{BASE}/coins/markets",
        params={
            "vs_currency": "usd",
            "category": "meme-token",
            "order": "volume_desc",
            "per_page": str(limit),
            "page": "1",
        },
    )


@cached(ttl=300, prefix="gecko")
async def get_market_chart(coin_id: str, days: int = 14) -> dict[str, Any]:
    """Get price history for RSI/MA calculations."""
    return await fetch_json(
        f"{BASE}/coins/{coin_id}/market_chart",
        params={"vs_currency": "usd", "days": str(days)},
    )


@cached(ttl=60, prefix="gecko")
async def get_coin_markets(ids: str | None = None, limit: int = 50) -> list[dict]:
    params: dict[str, str] = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": str(limit),
        "page": "1",
    }
    if ids:
        params["ids"] = ids
    return await fetch_json(f"{BASE}/coins/markets", params=params)
