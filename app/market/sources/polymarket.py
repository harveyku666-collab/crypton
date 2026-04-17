"""Polymarket data source — prediction market events via Gamma API (free, public)."""

from __future__ import annotations

import logging
from typing import Any

from app.common.http_client import fetch_json
from app.common.cache import cached

logger = logging.getLogger("bitinfo.polymarket")

GAMMA_BASE = "https://gamma-api.polymarket.com"


def _parse_outcome_price(raw: str | None) -> float | None:
    """Parse outcomePrices which can be JSON array string or comma-separated."""
    if not raw:
        return None
    try:
        import json as _json
        parsed = _json.loads(raw)
        if isinstance(parsed, list) and parsed:
            return float(parsed[0])
    except (ValueError, TypeError):
        pass
    try:
        parts = raw.split(",")
        if parts:
            return float(parts[0].strip().strip('"'))
    except (ValueError, TypeError):
        pass
    return None


def _parse_all_outcome_prices(raw: str | None) -> list[float]:
    """Parse all outcome prices."""
    if not raw:
        return []
    try:
        import json as _json
        parsed = _json.loads(raw)
        if isinstance(parsed, list):
            return [float(p) for p in parsed]
    except (ValueError, TypeError):
        pass
    try:
        return [float(p.strip().strip('"')) for p in raw.split(",") if p.strip()]
    except (ValueError, TypeError):
        return []


@cached(ttl=300, prefix="polymarket")
async def get_events(limit: int = 10, active: bool = True) -> list[dict[str, Any]]:
    """Fetch prediction market events from Polymarket Gamma API."""
    try:
        params: dict[str, Any] = {
            "limit": limit,
            "active": str(active).lower(),
            "closed": "false",
            "order": "volume24hr",
            "ascending": "false",
        }
        data = await fetch_json(f"{GAMMA_BASE}/events", params=params)
        if not isinstance(data, list):
            return []
        events = []
        for ev in data[:limit]:
            markets = ev.get("markets", [])
            top_market = markets[0] if markets else {}
            yes_price = None
            if top_market:
                prices_raw = top_market.get("outcomePrices", "")
                yes_price = _parse_outcome_price(prices_raw)
            events.append({
                "title": ev.get("title", ""),
                "slug": ev.get("slug", ""),
                "volume": float(ev.get("volume", 0) or 0),
                "volume_24h": float(ev.get("volume24hr", 0) or 0),
                "liquidity": float(ev.get("liquidity", 0) or 0),
                "start_date": ev.get("startDate"),
                "end_date": ev.get("endDate"),
                "category": ev.get("category", ""),
                "yes_price": yes_price,
                "market_count": len(markets),
                "source": "polymarket",
            })
        return events
    except Exception as e:
        logger.warning("Failed to fetch Polymarket events: %s", e)
        return []


@cached(ttl=300, prefix="polymarket")
async def get_markets(limit: int = 20, active: bool = True) -> list[dict[str, Any]]:
    """Fetch individual prediction markets."""
    try:
        params: dict[str, Any] = {
            "limit": limit,
            "active": str(active).lower(),
            "closed": "false",
            "order": "volume24hr",
            "ascending": "false",
        }
        data = await fetch_json(f"{GAMMA_BASE}/markets", params=params)
        if not isinstance(data, list):
            return []
        markets = []
        for m in data[:limit]:
            prices_raw = m.get("outcomePrices", "")
            price_list = _parse_all_outcome_prices(prices_raw)
            markets.append({
                "question": m.get("question", ""),
                "slug": m.get("groupItemTitle") or m.get("slug", ""),
                "volume": float(m.get("volume", 0) or 0),
                "volume_24h": float(m.get("volume24hr", 0) or 0),
                "liquidity": float(m.get("liquidity", 0) or 0),
                "yes_price": price_list[0] if price_list else None,
                "no_price": price_list[1] if len(price_list) > 1 else None,
                "end_date": m.get("endDate"),
                "source": "polymarket",
            })
        return markets
    except Exception as e:
        logger.warning("Failed to fetch Polymarket markets: %s", e)
        return []
