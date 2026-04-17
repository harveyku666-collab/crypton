"""DEX Screener data source — DEX trading pairs and trades (free, public)."""

from __future__ import annotations

import logging
from typing import Any

from app.common.http_client import fetch_json
from app.common.cache import cached

logger = logging.getLogger("bitinfo.dexscreener")

BASE_URL = "https://api.dexscreener.com"


@cached(ttl=60, prefix="dexscr")
async def get_token_pairs(address: str, limit: int = 20) -> list[dict[str, Any]]:
    """Get DEX trading pairs for a token address."""
    try:
        data = await fetch_json(f"{BASE_URL}/latest/dex/tokens/{address}")
        if not isinstance(data, dict):
            return []
        pairs = data.get("pairs") or []
        result = []
        for p in pairs[:limit]:
            result.append({
                "chain": p.get("chainId", ""),
                "dex": p.get("dexId", ""),
                "pair_address": p.get("pairAddress", ""),
                "base_token": {
                    "symbol": (p.get("baseToken") or {}).get("symbol", ""),
                    "name": (p.get("baseToken") or {}).get("name", ""),
                    "address": (p.get("baseToken") or {}).get("address", ""),
                },
                "quote_token": {
                    "symbol": (p.get("quoteToken") or {}).get("symbol", ""),
                },
                "price_usd": p.get("priceUsd"),
                "price_native": p.get("priceNative"),
                "volume_24h": float((p.get("volume") or {}).get("h24", 0) or 0),
                "price_change_24h": float((p.get("priceChange") or {}).get("h24", 0) or 0),
                "liquidity_usd": float((p.get("liquidity") or {}).get("usd", 0) or 0),
                "txns_24h_buys": (p.get("txns") or {}).get("h24", {}).get("buys", 0),
                "txns_24h_sells": (p.get("txns") or {}).get("h24", {}).get("sells", 0),
                "url": p.get("url", ""),
                "source": "dexscreener",
            })
        return result
    except Exception as e:
        logger.warning("Failed to fetch DEX pairs for %s: %s", address, e)
        return []


@cached(ttl=60, prefix="dexscr")
async def get_pair_detail(chain: str, pair_address: str) -> dict[str, Any] | None:
    """Get details for a specific DEX pair."""
    try:
        data = await fetch_json(f"{BASE_URL}/latest/dex/pairs/{chain}/{pair_address}")
        if not isinstance(data, dict):
            return None
        pairs = data.get("pairs") or []
        return pairs[0] if pairs else None
    except Exception as e:
        logger.warning("Failed to fetch pair detail: %s", e)
        return None
