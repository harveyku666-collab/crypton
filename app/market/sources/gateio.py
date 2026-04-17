"""Gate.io public Futures API — free, no API key required."""

from __future__ import annotations

from typing import Any

from app.common.http_client import fetch_json
from app.common.cache import cached

BASE = "https://api.gateio.ws/api/v4"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


@cached(ttl=30, prefix="gateio_oi")
async def get_open_interest(symbol: str = "BTC", settle: str = "usdt") -> dict[str, Any] | None:
    """Current open interest for a futures contract."""
    contract = f"{symbol.upper()}_{settle.upper()}"
    try:
        data = await fetch_json(
            f"{BASE}/futures/{settle}/contracts/{contract}",
            headers=HEADERS,
        )
        if not isinstance(data, dict) or "position_size" not in data:
            return None
        mark_price = float(data.get("mark_price") or 0)
        position_size = int(data.get("position_size") or 0)
        quanto_multiplier = float(data.get("quanto_multiplier") or 0.0001)
        oi_value = position_size * quanto_multiplier * mark_price
        return {
            "symbol": symbol.upper(),
            "exchange": "gate.io",
            "open_interest_contracts": position_size,
            "open_interest_usd": round(oi_value, 2),
            "mark_price": mark_price,
            "funding_rate": data.get("funding_rate"),
            "volume_24h_base": data.get("volume_24h_base"),
            "volume_24h_usd": data.get("volume_24h_quote"),
        }
    except Exception:
        return None


@cached(ttl=60, prefix="gateio_oi_hist")
async def get_open_interest_history(
    symbol: str = "BTC",
    settle: str = "usdt",
    limit: int = 24,
) -> list[dict[str, Any]]:
    """Historical OI + long/short ratio + liquidation data from contract_stats."""
    contract = f"{symbol.upper()}_{settle.upper()}"
    try:
        data = await fetch_json(
            f"{BASE}/futures/{settle}/contract_stats",
            params={"contract": contract, "limit": min(limit, 100)},
            headers=HEADERS,
        )
        if not isinstance(data, list):
            return []
        results = []
        for item in data:
            mark = float(item.get("mark_price") or 0)
            oi_contracts = int(item.get("open_interest") or 0)
            oi_usd = float(item.get("open_interest_usd") or 0)
            results.append({
                "timestamp": item.get("time"),
                "symbol": symbol.upper(),
                "exchange": "gate.io",
                "open_interest_contracts": oi_contracts,
                "open_interest_usd": round(oi_usd, 2),
                "mark_price": mark,
                "long_short_ratio_taker": item.get("lsr_taker"),
                "long_short_ratio_account": item.get("lsr_account"),
                "top_long_short_ratio": item.get("top_lsr_size"),
                "long_liq_usd": item.get("long_liq_usd"),
                "short_liq_usd": item.get("short_liq_usd"),
            })
        return results
    except Exception:
        return []
