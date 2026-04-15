"""Desk3 data source — ported from OpenClaw cryptocurrency-market-live-briefing."""

from __future__ import annotations

import asyncio
from typing import Any

from app.common.http_client import fetch_json
from app.common.cache import cached

API1 = "https://api1.desk3.io/v1"
MCP = "https://mcp.desk3.io/v1"
HEADERS = {"language": "en"}


@cached(ttl=10, prefix="desk3")
async def get_prices(symbols: str = "BTCUSDT,ETHUSDT,SOLUSDT") -> list[dict]:
    data = await fetch_json(f"{API1}/market/mini/24hr", params={"symbol": symbols}, headers=HEADERS)
    return data if isinstance(data, list) else []


async def get_core_prices() -> dict[str, dict[str, float]]:
    raw = await get_prices("BTCUSDT,ETHUSDT,SOLUSDT")
    mapping = {"BTCUSDT": "BTC", "ETHUSDT": "ETH", "SOLUSDT": "SOL"}
    result: dict[str, dict[str, float]] = {}
    for item in raw:
        sym = mapping.get(item.get("s", ""))
        if sym:
            result[sym] = {"price": float(item.get("c", 0)), "change_pct": float(item.get("P", 0))}
    return result


@cached(ttl=10, prefix="desk3")
async def get_trending(limit: int = 10) -> list[dict]:
    raw = await get_prices()
    valid = [i for i in raw if float(i.get("q", 0)) > 0]
    valid.sort(key=lambda x: float(x.get("q", 0)), reverse=True)
    return valid[:limit]


@cached(ttl=60, prefix="desk3")
async def get_fear_greed() -> dict[str, Any] | None:
    data = await fetch_json(f"{MCP}/market/fear-greed", headers=HEADERS)
    if data.get("code") != 0:
        return None
    hist = data.get("data", {}).get("data", {}).get("historicalValues") or data.get("data", {}).get("historicalValues")
    return hist


@cached(ttl=60, prefix="desk3")
async def get_altcoin_season() -> dict[str, Any] | None:
    data = await fetch_json(f"{MCP}/market/altcoin/season", headers=HEADERS)
    return data.get("data") if data.get("code") == 0 else None


@cached(ttl=300, prefix="desk3")
async def get_puell_multiple() -> dict[str, Any] | None:
    data = await fetch_json(f"{API1}/market/puell-multiple", headers=HEADERS)
    if data.get("code") != 0:
        return None
    pts = data.get("data", {}).get("points", [])
    if not pts:
        return None
    return {"current": pts[-1], "week_ago": pts[-7] if len(pts) >= 7 else None}


@cached(ttl=300, prefix="desk3")
async def get_dominance() -> dict[str, float | None] | None:
    data = await fetch_json(f"{API1}/market/bitcoin/dominance", headers=HEADERS)
    if data.get("code") != 0:
        return None
    pts = data.get("data", {}).get("points", [])
    if not pts:
        return None
    dom = pts[-1].get("dominance", [])
    return {
        "btc": dom[0] if len(dom) > 0 else None,
        "eth": dom[1] if len(dom) > 1 else None,
        "others": dom[2] if len(dom) > 2 else None,
    }


@cached(ttl=300, prefix="desk3")
async def get_cycles() -> dict[str, Any] | None:
    data = await fetch_json(f"{MCP}/market/cycles", headers=HEADERS)
    return data.get("data") if data.get("code") == 0 else None


@cached(ttl=300, prefix="desk3")
async def get_cycle_indicators() -> dict[str, Any] | None:
    data = await fetch_json(f"{MCP}/market/cycleIndicators", headers=HEADERS)
    return data.get("data") if data.get("code") == 0 else None


@cached(ttl=60, prefix="desk3")
async def get_btc_trend(tail: int = 10) -> list:
    data = await fetch_json(f"{MCP}/market/btc/trend", headers=HEADERS)
    entries = data.get("data", []) if data.get("code") == 0 else []
    return entries[-tail:] if entries else []


@cached(ttl=60, prefix="desk3")
async def get_eth_trend(tail: int = 10) -> list:
    data = await fetch_json(f"{MCP}/market/eth/trend", headers=HEADERS)
    entries = data.get("data", []) if data.get("code") == 0 else []
    return entries[-tail:] if entries else []


@cached(ttl=3600, prefix="desk3")
async def get_exchange_rate() -> dict[str, Any] | None:
    data = await fetch_json(f"{MCP}/market/exchangeRate", headers=HEADERS)
    return data.get("data", data)


@cached(ttl=3600, prefix="desk3")
async def get_calendar(date: str | None = None) -> list[dict]:
    from datetime import date as dt_date
    d = date or dt_date.today().isoformat()
    data = await fetch_json(f"{API1}/market/calendar", params={"date": d}, headers=HEADERS)
    if data.get("code") != 0:
        return []
    entries = data.get("data", [])
    if entries and isinstance(entries, list):
        return entries[0].get("events", [])
    return []


async def get_full_briefing() -> dict[str, Any]:
    tasks = {
        "core_prices": get_core_prices(),
        "fear_greed": get_fear_greed(),
        "puell_multiple": get_puell_multiple(),
        "dominance": get_dominance(),
        "trending": get_trending(10),
    }
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    return {
        k: (None if isinstance(v, BaseException) else v)
        for k, v in zip(tasks.keys(), results)
    }
