"""GeckoTerminal public API — on-chain token price by contract address."""

from __future__ import annotations

from typing import Any

from app.common.cache import cached
from app.common.http_client import fetch_json

BASE = "https://api.geckoterminal.com/api/v2"
NETWORK_IDS = {
    "arbitrum": "arbitrum",
    "avalanche": "avax",
    "base": "base",
    "bsc": "bsc",
    "ethereum": "eth",
    "optimism": "optimism",
    "polygon": "polygon_pos",
    "solana": "solana",
}


def _safe_float(value: Any) -> float | None:
    try:
        if value in {None, ""}:
            return None
        return float(value)
    except Exception:
        return None


@cached(ttl=120, prefix="geckoterminal")
async def get_token_price(blockchain: str, contract_address: str) -> dict[str, Any] | None:
    network_id = NETWORK_IDS.get(str(blockchain or "").strip().lower())
    normalized_address = str(contract_address or "").strip().lower()
    if not network_id or not normalized_address:
        return None

    data = await fetch_json(f"{BASE}/networks/{network_id}/tokens/{normalized_address}")
    payload = data.get("data") if isinstance(data, dict) else None
    attributes = payload.get("attributes") if isinstance(payload, dict) else None
    if not isinstance(attributes, dict):
        return None

    price = _safe_float(attributes.get("price_usd"))
    if price is None or price <= 0:
        return None

    volume_24h = attributes.get("volume_usd") if isinstance(attributes.get("volume_usd"), dict) else {}
    return {
        "symbol": str(attributes.get("symbol") or "").upper() or None,
        "name": attributes.get("name"),
        "price": price,
        "fdv_usd": _safe_float(attributes.get("fdv_usd")),
        "market_cap": _safe_float(attributes.get("market_cap_usd")),
        "liquidity_usd": _safe_float(attributes.get("total_reserve_in_usd")),
        "volume_24h": _safe_float(volume_24h.get("h24")) if isinstance(volume_24h, dict) else None,
        "source": "geckoterminal",
        "network": network_id,
        "contract_address": normalized_address,
        "coingecko_coin_id": attributes.get("coingecko_coin_id"),
    }
