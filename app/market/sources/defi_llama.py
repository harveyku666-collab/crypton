"""DefiLlama data source — ported from defi-yield-scanner."""

from __future__ import annotations

import logging
from typing import Any

from app.common.http_client import fetch_json
from app.common.cache import cached

logger = logging.getLogger("bitinfo.defi_llama")

LLAMA_BASE = "https://api.llama.fi"
YIELDS_URL = "https://yields.llama.fi/pools"
BRIDGES_URL = "https://bridges.llama.fi"


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


@cached(ttl=300, prefix="llama")
async def get_yield_ranking(limit: int = 20, sort_by: str = "apy", min_tvl: float = 100_000) -> list[dict]:
    """Yield ranking suitable for the /onchain/yield-ranking endpoint.

    Wraps scan_yields with sensible defaults and returns a format
    compatible with what the Surf endpoint previously returned.
    """
    pools = await get_yield_pools()
    filtered = []
    for p in pools:
        apy = p.get("apy") or 0
        tvl = p.get("tvlUsd") or 0
        if tvl < min_tvl or apy <= 0:
            continue
        filtered.append({
            "pool": p.get("pool", ""),
            "project": p.get("project", ""),
            "chain": p.get("chain", ""),
            "symbol": p.get("symbol", ""),
            "apy": round(apy, 2),
            "apy_base": round(p.get("apyBase") or 0, 2),
            "apy_reward": round(p.get("apyReward") or 0, 2),
            "tvl": round(tvl, 2),
            "stable_coin": p.get("stablecoin", False),
            "source": "defillama",
        })
    key = "apy" if sort_by == "apy" else "tvl"
    filtered.sort(key=lambda x: x.get(key, 0), reverse=True)
    return filtered[:limit]


@cached(ttl=600, prefix="llama")
async def get_bridge_ranking(limit: int = 20) -> list[dict]:
    """Cross-chain bridge ranking from DefiLlama Bridges API."""
    try:
        data = await fetch_json(f"{BRIDGES_URL}/bridges", params={"includeChains": "true"})
    except Exception as e:
        logger.warning("Failed to fetch bridge ranking: %s", e)
        return []
    if not isinstance(data, dict):
        return []
    bridges = data.get("bridges", [])
    if not isinstance(bridges, list):
        return []
    result = []
    for b in bridges:
        vol_prev_day = b.get("lastDailyVolume") or b.get("currentDayVolume") or 0
        result.append({
            "name": b.get("displayName") or b.get("name", ""),
            "chains": b.get("chains", []),
            "volume_24h": round(float(vol_prev_day), 2),
            "source": "defillama",
        })
    result.sort(key=lambda x: x["volume_24h"], reverse=True)
    return result[:limit]
