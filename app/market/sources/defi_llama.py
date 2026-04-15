"""DefiLlama data source — ported from defi-yield-scanner."""

from __future__ import annotations

from typing import Any

from app.common.http_client import fetch_json
from app.common.cache import cached

LLAMA_BASE = "https://api.llama.fi"
YIELDS_URL = "https://yields.llama.fi/pools"


@cached(ttl=300, prefix="llama")
async def get_protocols() -> list[dict]:
    return await fetch_json(f"{LLAMA_BASE}/protocols")


@cached(ttl=300, prefix="llama")
async def get_protocol_tvl(slug: str) -> dict[str, Any]:
    return await fetch_json(f"{LLAMA_BASE}/protocol/{slug}")


@cached(ttl=300, prefix="llama")
async def get_yield_pools() -> list[dict]:
    data = await fetch_json(YIELDS_URL)
    if isinstance(data, dict) and data.get("status") == "success":
        return data.get("data", [])
    return data if isinstance(data, list) else []


async def scan_yields(
    min_apy: float = 1.0,
    min_tvl: float = 1_000_000,
    chain: str | None = None,
    symbol: str | None = None,
    limit: int = 50,
) -> list[dict]:
    pools = await get_yield_pools()
    filtered = []
    for p in pools:
        apy = p.get("apy") or 0
        tvl = p.get("tvlUsd") or 0
        if apy < min_apy or tvl < min_tvl:
            continue
        if chain and p.get("chain", "").lower() != chain.lower():
            continue
        if symbol and symbol.upper() not in (p.get("symbol") or "").upper():
            continue
        filtered.append({
            "pool": p.get("pool", ""),
            "project": p.get("project", ""),
            "chain": p.get("chain", ""),
            "symbol": p.get("symbol", ""),
            "apy": round(apy, 2),
            "tvl": round(tvl, 2),
            "apy_base": round(p.get("apyBase") or 0, 2),
            "apy_reward": round(p.get("apyReward") or 0, 2),
        })
    filtered.sort(key=lambda x: x["apy"], reverse=True)
    return filtered[:limit]
