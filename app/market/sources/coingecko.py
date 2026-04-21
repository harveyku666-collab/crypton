"""CoinGecko data source — ported from crypto-tracker-cn."""

from __future__ import annotations

from typing import Any

from app.common.http_client import fetch_json
from app.common.cache import cached

BASE = "https://api.coingecko.com/api/v3"
FNG_URL = "https://api.alternative.me/fng"


def _safe_float(value: Any) -> float | None:
    try:
        if value in {None, ""}:
            return None
        return float(value)
    except Exception:
        return None


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


@cached(ttl=120, prefix="gecko")
async def search_coins(query: str) -> list[dict[str, Any]]:
    data = await fetch_json(f"{BASE}/search", params={"query": query})
    rows = data.get("coins") or []
    return rows if isinstance(rows, list) else []


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


@cached(ttl=120, prefix="gecko_symbol")
async def get_price_by_symbol(symbol: str) -> dict[str, Any] | None:
    normalized_symbol = str(symbol or "").strip().upper()
    if not normalized_symbol:
        return None

    matches = []
    for item in await search_coins(normalized_symbol):
        candidate_symbol = str(item.get("symbol") or "").strip().upper()
        if candidate_symbol != normalized_symbol:
            continue
        rank = item.get("market_cap_rank")
        try:
            market_cap_rank = int(rank) if rank not in {None, ""} else 999999
        except Exception:
            market_cap_rank = 999999
        matches.append(
            {
                "id": item.get("id"),
                "symbol": candidate_symbol,
                "name": item.get("name"),
                "market_cap_rank": market_cap_rank,
            }
        )

    if not matches:
        return None

    matches.sort(key=lambda item: (item["market_cap_rank"], str(item.get("id") or "")))
    coin_id = str(matches[0].get("id") or "").strip()
    if not coin_id:
        return None

    markets = await get_coin_markets(ids=coin_id, limit=1)
    row = markets[0] if isinstance(markets, list) and markets else None
    if not isinstance(row, dict):
        return None

    price = _safe_float(row.get("current_price"))
    if price is None or price <= 0:
        return None

    return {
        "symbol": normalized_symbol,
        "price": price,
        "change_pct": _safe_float(row.get("price_change_percentage_24h")),
        "market_cap": _safe_float(row.get("market_cap")),
        "volume": _safe_float(row.get("total_volume")),
        "high": _safe_float(row.get("high_24h")),
        "low": _safe_float(row.get("low_24h")),
        "source": "coingecko",
        "gecko_id": coin_id,
        "name": row.get("name") or matches[0].get("name"),
    }
