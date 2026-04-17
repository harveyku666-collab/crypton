"""Surf CLI data source — crypto intelligence via asksurf.ai.

Calls the `surf` CLI binary as a subprocess. No HTTP whitelist needed since
data flows through a local binary, not outbound HTTP from this process.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from typing import Any

from app.common.cache import cached

logger = logging.getLogger("bitinfo.surf")

_SURF_BIN: str | None = None


def _find_surf() -> str:
    global _SURF_BIN
    if _SURF_BIN:
        return _SURF_BIN
    import os
    candidates = [
        os.path.expanduser("~/.local/bin/surf"),
        shutil.which("surf") or "",
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            _SURF_BIN = c
            return c
    raise FileNotFoundError("surf CLI not found. Install: curl -fsSL https://agent.asksurf.ai/cli/releases/install.sh | sh")


async def _run_surf(*args: str, stdin: str | None = None, timeout: float = 20.0) -> dict[str, Any] | list | None:
    """Run a surf CLI command and return parsed JSON."""
    cmd = [_find_surf(), *args, "--json"]
    logger.debug("surf cmd: %s", " ".join(cmd))
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if stdin else None,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=stdin.encode() if stdin else None),
            timeout=timeout,
        )
        if proc.returncode != 0:
            err_text = stderr.decode().strip() if stderr else ""
            logger.warning("surf exited %d: %s | stderr: %s", proc.returncode, " ".join(args), err_text)
            try:
                err_json = json.loads(stdout.decode()) if stdout else {}
                return err_json
            except json.JSONDecodeError:
                return None
        raw = stdout.decode().strip()
        if not raw:
            return None
        return json.loads(raw)
    except asyncio.TimeoutError:
        logger.error("surf timed out: %s", " ".join(args))
        return None
    except Exception as e:
        logger.error("surf error: %s — %s", " ".join(args), e)
        return None


def _extract_data(result: dict | list | None) -> Any:
    """Extract the `data` field from Surf's response envelope."""
    if result is None:
        return None
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        if "error" in result and result.get("error"):
            logger.warning("Surf API error: %s", result["error"])
            return None
        return result.get("data", result)
    return result


# ──────────────────────────────────────────────────────────────
# Market data
# ──────────────────────────────────────────────────────────────

@cached(ttl=30, prefix="surf")
async def get_price(symbol: str = "BTC") -> dict[str, Any] | None:
    """Current price data for a symbol."""
    result = await _run_surf("market-price", "--symbol", symbol.upper(), "--time-range", "1d")
    data = _extract_data(result)
    if not data:
        return None
    if isinstance(data, list) and data:
        latest = data[-1]
        return {
            "symbol": symbol.upper(),
            "price": latest.get("value"),
            "timestamp": latest.get("timestamp"),
            "source": "surf",
        }
    return None


@cached(ttl=30, prefix="surf")
async def get_prices_multi(symbols: list[str]) -> list[dict[str, Any]]:
    """Fetch prices for multiple symbols concurrently."""
    tasks = [get_price(s) for s in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if isinstance(r, dict)]


@cached(ttl=60, prefix="surf")
async def get_market_ranking(limit: int = 20, sort_by: str = "market_cap") -> list[dict[str, Any]]:
    result = await _run_surf("market-ranking", "--sort-by", sort_by, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=120, prefix="surf")
async def get_fear_greed() -> dict[str, Any] | None:
    """Fear & Greed Index with history. Surf returns newest-first."""
    result = await _run_surf("market-fear-greed")
    data = _extract_data(result)
    if not data or not isinstance(data, list) or len(data) == 0:
        return None
    latest = data[0]
    yesterday = data[1] if len(data) >= 2 else None
    last_week = data[7] if len(data) > 7 else (data[-1] if len(data) >= 3 else None)
    return {
        "now": {
            "score": latest.get("value"),
            "name": latest.get("classification") or _fg_label(latest.get("value")),
            "timestamp": latest.get("timestamp"),
        },
        "yesterday": {
            "score": yesterday.get("value"),
            "name": yesterday.get("classification") or _fg_label(yesterday.get("value")),
        } if yesterday else None,
        "lastWeek": {
            "score": last_week.get("value"),
            "name": last_week.get("classification") or _fg_label(last_week.get("value")),
        } if last_week else None,
        "source": "surf",
    }


def _fg_label(value: Any) -> str:
    if value is None:
        return ""
    v = int(value) if not isinstance(value, int) else value
    if v <= 25:
        return "Extreme Fear"
    if v <= 45:
        return "Fear"
    if v <= 55:
        return "Neutral"
    if v <= 75:
        return "Greed"
    return "Extreme Greed"


# ──────────────────────────────────────────────────────────────
# Technical indicators
# ──────────────────────────────────────────────────────────────

@cached(ttl=30, prefix="surf")
async def get_indicator(indicator: str, symbol: str = "BTC", interval: str = "4h") -> dict[str, Any] | None:
    """Fetch a technical indicator (rsi, macd, bollinger, etc.)."""
    result = await _run_surf(
        "market-price-indicator",
        "--indicator", indicator.lower(),
        "--symbol", symbol.upper(),
        "--interval", interval,
    )
    data = _extract_data(result)
    if isinstance(data, list) and data:
        return data[-1] if len(data) == 1 else {"values": data}
    if isinstance(data, dict):
        return data
    return None


@cached(ttl=30, prefix="surf")
async def get_all_indicators(symbol: str = "BTC", interval: str = "4h") -> dict[str, Any]:
    """Fetch RSI, MACD, Bollinger for a symbol."""
    rsi_task = get_indicator("rsi", symbol, interval)
    macd_task = get_indicator("macd", symbol, interval)
    boll_task = get_indicator("bollinger", symbol, interval)
    rsi, macd, boll = await asyncio.gather(rsi_task, macd_task, boll_task, return_exceptions=True)
    return {
        "rsi": rsi if not isinstance(rsi, BaseException) else None,
        "macd": macd if not isinstance(macd, BaseException) else None,
        "bollinger": boll if not isinstance(boll, BaseException) else None,
    }


# ──────────────────────────────────────────────────────────────
# Exchange data (funding rates, klines)
# ──────────────────────────────────────────────────────────────

@cached(ttl=60, prefix="surf")
async def get_klines(pair: str = "BTC/USDT", interval: str = "15m", limit: int = 50) -> list[dict[str, Any]]:
    result = await _run_surf(
        "exchange-klines",
        "--pair", pair,
        "--interval", interval,
        "--limit", str(limit),
    )
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=120, prefix="surf")
async def get_funding_rates_multi() -> list[dict[str, Any]]:
    """Get funding rates across exchanges from Surf market-futures."""
    result = await _run_surf("market-futures", "--sort-by", "funding_rate", "--order", "desc")
    data = _extract_data(result)
    if not isinstance(data, list):
        return []
    rates = []
    for item in data:
        rate = item.get("funding_rate") or item.get("fundingRate")
        if rate is None:
            continue
        rates.append({
            "symbol": (item.get("symbol") or item.get("pair", "")).replace("/USDT", "").replace("USDT", ""),
            "rate": float(rate),
            "rate_pct": float(rate) * 100,
            "price": float(item.get("price") or item.get("last_price") or 0),
            "volume_24h": float(item.get("volume_24h") or item.get("quoteVolume") or 0),
            "open_interest": float(item.get("open_interest") or item.get("openInterest") or 0),
            "exchange": item.get("exchange", ""),
            "source": "surf",
        })
    rates.sort(key=lambda x: abs(x["rate"]), reverse=True)
    return rates


@cached(ttl=120, prefix="surf")
async def get_funding_history(pair: str = "BTC/USDT", limit: int = 20) -> list[dict[str, Any]]:
    result = await _run_surf("exchange-funding-history", "--pair", pair, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


# ──────────────────────────────────────────────────────────────
# Social / sentiment
# ──────────────────────────────────────────────────────────────

@cached(ttl=300, prefix="surf")
async def get_social_sentiment(query: str) -> dict[str, Any] | None:
    """Social sentiment for a project/token."""
    result = await _run_surf("social-sentiment", "--q", query)
    data = _extract_data(result)
    return data if isinstance(data, dict) else None


@cached(ttl=300, prefix="surf")
async def get_social_mindshare_ranking(limit: int = 10, time_range: str = "24h") -> list[dict[str, Any]]:
    """Top projects by social mindshare."""
    result = await _run_surf("social-ranking", "--limit", str(limit), "--time-range", time_range)
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=300, prefix="surf")
async def get_social_user(handle: str) -> dict[str, Any] | None:
    """Get social profile for a Twitter/X user."""
    result = await _run_surf("social-user", "--handle", handle)
    data = _extract_data(result)
    return data if isinstance(data, dict) else None


@cached(ttl=300, prefix="surf")
async def get_social_user_posts(handle: str, limit: int = 10) -> list[dict[str, Any]]:
    result = await _run_surf("social-user-posts", "--handle", handle, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


# ──────────────────────────────────────────────────────────────
# Liquidation data
# ──────────────────────────────────────────────────────────────

@cached(ttl=60, prefix="surf")
async def get_liquidation_chart(symbol: str = "BTC", interval: str = "1h", limit: int = 24) -> list[dict[str, Any]]:
    result = await _run_surf(
        "market-liquidation-chart",
        "--symbol", symbol.upper(),
        "--interval", interval,
        "--limit", str(limit),
    )
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=60, prefix="surf")
async def get_liquidation_by_exchange(symbol: str = "BTC", time_range: str = "24h") -> list[dict[str, Any]]:
    result = await _run_surf(
        "market-liquidation-exchange-list",
        "--symbol", symbol.upper(),
        "--time-range", time_range,
    )
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=60, prefix="surf")
async def get_large_liquidations(symbol: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    args = ["market-liquidation-order", "--sort-by", "amount", "--order", "desc"]
    if symbol:
        args.extend(["--symbol", symbol.upper()])
    result = await _run_surf(*args)
    data = _extract_data(result)
    return data[:limit] if isinstance(data, list) else []


# ──────────────────────────────────────────────────────────────
# Wallet / On-chain
# ──────────────────────────────────────────────────────────────

@cached(ttl=300, prefix="surf")
async def get_wallet_detail(address: str, chain: str = "ethereum") -> dict[str, Any] | None:
    result = await _run_surf("wallet-detail", "--address", address, "--chain", chain)
    data = _extract_data(result)
    return data if isinstance(data, dict) else None


# ──────────────────────────────────────────────────────────────
# Prediction markets
# ──────────────────────────────────────────────────────────────

@cached(ttl=300, prefix="surf")
async def get_polymarket_events(limit: int = 10) -> list[dict[str, Any]]:
    result = await _run_surf("polymarket-events", "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


# ──────────────────────────────────────────────────────────────
# News
# ──────────────────────────────────────────────────────────────

@cached(ttl=300, prefix="surf")
async def get_news_feed(limit: int = 10) -> list[dict[str, Any]]:
    result = await _run_surf("news-feed", "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


# ──────────────────────────────────────────────────────────────
# DeFi yields
# ──────────────────────────────────────────────────────────────

@cached(ttl=300, prefix="surf")
async def get_yield_ranking(limit: int = 20, sort_by: str = "apy") -> list[dict[str, Any]]:
    result = await _run_surf("onchain-yield-ranking", "--sort-by", sort_by, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


# ──────────────────────────────────────────────────────────────
# Exchange data (advanced)
# ──────────────────────────────────────────────────────────────

@cached(ttl=10, prefix="surf")
async def get_exchange_depth(pair: str = "BTC/USDT", exchange: str = "binance") -> dict[str, Any] | None:
    result = await _run_surf("exchange-depth", "--pair", pair, "--exchange", exchange)
    data = _extract_data(result)
    return data if isinstance(data, dict) else None


@cached(ttl=60, prefix="surf")
async def get_long_short_ratio(pair: str = "BTC/USDT", interval: str = "1h", limit: int = 24) -> list[dict[str, Any]]:
    result = await _run_surf("exchange-long-short-ratio", "--pair", pair, "--interval", interval, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=300, prefix="surf")
async def get_exchange_markets(exchange: str = "binance", market_type: str = "spot") -> list[dict[str, Any]]:
    result = await _run_surf("exchange-markets", "--exchange", exchange, "--market-type", market_type)
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=30, prefix="surf")
async def get_exchange_perp(symbol: str = "BTC", sort_by: str = "open_interest") -> list[dict[str, Any]]:
    result = await _run_surf("exchange-perp", "--symbol", symbol.upper(), "--sort-by", sort_by)
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=30, prefix="surf")
async def get_exchange_price(pair: str = "BTC/USDT", exchange: str = "binance") -> dict[str, Any] | None:
    result = await _run_surf("exchange-price", "--pair", pair, "--exchange", exchange)
    data = _extract_data(result)
    return data if isinstance(data, dict) else None


# ──────────────────────────────────────────────────────────────
# Market — ETF, Options, On-chain Indicators, Events
# ──────────────────────────────────────────────────────────────

@cached(ttl=300, prefix="surf")
async def get_etf_flows(symbol: str = "BTC", limit: int = 30) -> list[dict[str, Any]]:
    result = await _run_surf("market-etf", "--symbol", symbol.upper(), "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=60, prefix="surf")
async def get_options(symbol: str = "BTC") -> dict[str, Any] | None:
    result = await _run_surf("market-options", "--symbol", symbol.upper())
    data = _extract_data(result)
    return data if isinstance(data, (dict, list)) else None


@cached(ttl=120, prefix="surf")
async def get_onchain_indicator(indicator: str, symbol: str = "BTC", limit: int = 30) -> list[dict[str, Any]]:
    result = await _run_surf("market-onchain-indicator", "--indicator", indicator, "--symbol", symbol.upper(), "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=3600, prefix="surf")
async def get_listing_events(limit: int = 20) -> list[dict[str, Any]]:
    result = await _run_surf("listing", "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=3600, prefix="surf")
async def get_tge_events(limit: int = 20) -> list[dict[str, Any]]:
    result = await _run_surf("market-tge", "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=3600, prefix="surf")
async def get_public_sales(limit: int = 20) -> list[dict[str, Any]]:
    result = await _run_surf("market-public-sale", "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


# ──────────────────────────────────────────────────────────────
# Prediction markets — Polymarket full suite
# ──────────────────────────────────────────────────────────────

@cached(ttl=300, prefix="surf")
async def get_polymarket_leaderboard(limit: int = 20) -> list[dict[str, Any]]:
    result = await _run_surf("polymarket-leaderboard", "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=300, prefix="surf")
async def get_polymarket_markets(event_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    args = ["polymarket-markets", "--limit", str(limit)]
    if event_id:
        args.extend(["--event-id", event_id])
    result = await _run_surf(*args)
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=120, prefix="surf")
async def get_polymarket_open_interest(market_id: str, interval: str = "1d", limit: int = 30) -> list[dict[str, Any]]:
    result = await _run_surf("polymarket-open-interest", "--market-id", market_id, "--interval", interval, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=30, prefix="surf")
async def get_polymarket_orderbooks(market_id: str) -> dict[str, Any] | None:
    result = await _run_surf("polymarket-orderbooks", "--market-id", market_id)
    data = _extract_data(result)
    return data if isinstance(data, dict) else None


@cached(ttl=300, prefix="surf")
async def get_polymarket_positions(address: str, limit: int = 20) -> list[dict[str, Any]]:
    result = await _run_surf("polymarket-positions", "--address", address, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=60, prefix="surf")
async def get_polymarket_ohlcv(market_id: str, interval: str = "1d", limit: int = 30) -> list[dict[str, Any]]:
    result = await _run_surf("polymarket-price-ohlcv", "--market-id", market_id, "--interval", interval, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=60, prefix="surf")
async def get_polymarket_prices(market_id: str, interval: str = "1h", limit: int = 48) -> list[dict[str, Any]]:
    result = await _run_surf("polymarket-prices", "--market-id", market_id, "--interval", interval, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=300, prefix="surf")
async def get_polymarket_smart_money(limit: int = 10, view: str = "overview") -> list[dict[str, Any]]:
    result = await _run_surf("polymarket-smart-money", "--view", view, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=60, prefix="surf")
async def get_polymarket_trades(market_id: str, limit: int = 50) -> list[dict[str, Any]]:
    result = await _run_surf("polymarket-trades", "--market-id", market_id, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=120, prefix="surf")
async def get_polymarket_volume_split(market_id: str, interval: str = "1d", limit: int = 30) -> list[dict[str, Any]]:
    result = await _run_surf("polymarket-volume-split", "--market-id", market_id, "--interval", interval, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=120, prefix="surf")
async def get_polymarket_volumes(market_id: str, interval: str = "1d", limit: int = 30) -> list[dict[str, Any]]:
    result = await _run_surf("polymarket-volumes", "--market-id", market_id, "--interval", interval, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


# ──────────────────────────────────────────────────────────────
# Prediction markets — Kalshi full suite
# ──────────────────────────────────────────────────────────────

@cached(ttl=300, prefix="surf")
async def get_kalshi_events(limit: int = 20) -> list[dict[str, Any]]:
    result = await _run_surf("kalshi-events", "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=300, prefix="surf")
async def get_kalshi_markets(event_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    args = ["kalshi-markets", "--limit", str(limit)]
    if event_id:
        args.extend(["--event-id", event_id])
    result = await _run_surf(*args)
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=120, prefix="surf")
async def get_kalshi_open_interest(market_id: str, interval: str = "1d", limit: int = 30) -> list[dict[str, Any]]:
    result = await _run_surf("kalshi-open-interest", "--market-id", market_id, "--interval", interval, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=30, prefix="surf")
async def get_kalshi_orderbooks(market_id: str) -> dict[str, Any] | None:
    result = await _run_surf("kalshi-orderbooks", "--market-id", market_id)
    data = _extract_data(result)
    return data if isinstance(data, dict) else None


@cached(ttl=60, prefix="surf")
async def get_kalshi_prices(market_id: str, interval: str = "1h", limit: int = 48) -> list[dict[str, Any]]:
    result = await _run_surf("kalshi-prices", "--market-id", market_id, "--interval", interval, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=60, prefix="surf")
async def get_kalshi_trades(market_id: str, limit: int = 50) -> list[dict[str, Any]]:
    result = await _run_surf("kalshi-trades", "--market-id", market_id, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=120, prefix="surf")
async def get_kalshi_volumes(market_id: str, interval: str = "1d", limit: int = 30) -> list[dict[str, Any]]:
    result = await _run_surf("kalshi-volumes", "--market-id", market_id, "--interval", interval, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


# ──────────────────────────────────────────────────────────────
# Cross-platform prediction markets
# ──────────────────────────────────────────────────────────────

@cached(ttl=300, prefix="surf")
async def get_matching_market_daily() -> list[dict[str, Any]]:
    result = await _run_surf("matching-market-daily")
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=300, prefix="surf")
async def get_matching_market_pairs(limit: int = 20) -> list[dict[str, Any]]:
    result = await _run_surf("matching-market-pairs", "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=300, prefix="surf")
async def get_prediction_analytics(limit: int = 20) -> list[dict[str, Any]]:
    result = await _run_surf("prediction-market-analytics", "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=300, prefix="surf")
async def get_prediction_correlations(limit: int = 20) -> list[dict[str, Any]]:
    result = await _run_surf("prediction-market-correlations", "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


# ──────────────────────────────────────────────────────────────
# On-chain advanced
# ──────────────────────────────────────────────────────────────

@cached(ttl=30, prefix="surf")
async def get_gas_price(chain: str = "ethereum") -> dict[str, Any] | None:
    result = await _run_surf("onchain-gas-price", "--chain", chain)
    data = _extract_data(result)
    return data if isinstance(data, dict) else None


@cached(ttl=60, prefix="surf")
async def get_onchain_sql(query: str, chain: str = "ethereum") -> dict[str, Any] | None:
    result = await _run_surf("onchain-sql", "--chain", chain, stdin=query, timeout=30.0)
    data = _extract_data(result)
    return data


@cached(ttl=60, prefix="surf")
async def get_onchain_structured_query(table: str, chain: str = "ethereum", limit: int = 100, **filters: str) -> list[dict[str, Any]]:
    args = ["onchain-structured-query", "--table", table, "--chain", chain, "--limit", str(limit)]
    for k, v in filters.items():
        args.extend([f"--{k}", v])
    result = await _run_surf(*args)
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=300, prefix="surf")
async def get_onchain_schema(chain: str = "ethereum") -> dict[str, Any] | None:
    result = await _run_surf("onchain-schema", "--chain", chain)
    data = _extract_data(result)
    return data


@cached(ttl=60, prefix="surf")
async def get_tx_detail(tx_hash: str, chain: str = "ethereum") -> dict[str, Any] | None:
    result = await _run_surf("onchain-tx", "--hash", tx_hash, "--chain", chain)
    data = _extract_data(result)
    return data if isinstance(data, dict) else None


@cached(ttl=300, prefix="surf")
async def get_bridge_ranking(limit: int = 20) -> list[dict[str, Any]]:
    result = await _run_surf("onchain-bridge-ranking", "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


# ──────────────────────────────────────────────────────────────
# Wallet advanced
# ──────────────────────────────────────────────────────────────

@cached(ttl=300, prefix="surf")
async def get_wallet_history(address: str, chain: str = "ethereum", limit: int = 20) -> list[dict[str, Any]]:
    result = await _run_surf("wallet-history", "--address", address, "--chain", chain, "--limit", str(limit), "--sort-by", "timestamp", "--order", "desc")
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=300, prefix="surf")
async def get_wallet_transfers(address: str, chain: str = "ethereum", limit: int = 20) -> list[dict[str, Any]]:
    result = await _run_surf("wallet-transfers", "--address", address, "--chain", chain, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=300, prefix="surf")
async def get_wallet_net_worth(address: str, time_range: str = "30d") -> list[dict[str, Any]]:
    result = await _run_surf("wallet-net-worth", "--address", address, "--time-range", time_range)
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=3600, prefix="surf")
async def get_wallet_labels_batch(addresses: list[str]) -> list[dict[str, Any]]:
    addr_str = ",".join(addresses)
    result = await _run_surf("wallet-labels-batch", "--addresses", addr_str)
    data = _extract_data(result)
    return data if isinstance(data, list) else []


# ──────────────────────────────────────────────────────────────
# Token advanced
# ──────────────────────────────────────────────────────────────

@cached(ttl=120, prefix="surf")
async def get_token_holders(address: str, chain: str = "ethereum", limit: int = 20) -> list[dict[str, Any]]:
    result = await _run_surf("token-holders", "--address", address, "--chain", chain, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=120, prefix="surf")
async def get_token_tokenomics(symbol: str) -> list[dict[str, Any]]:
    result = await _run_surf("token-tokenomics", "--symbol", symbol.upper())
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=60, prefix="surf")
async def get_token_dex_trades(address: str, chain: str = "ethereum", limit: int = 50) -> list[dict[str, Any]]:
    result = await _run_surf("token-dex-trades", "--address", address, "--chain", chain, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=120, prefix="surf")
async def get_token_transfers(address: str, chain: str = "ethereum", limit: int = 50) -> list[dict[str, Any]]:
    result = await _run_surf("token-transfers", "--address", address, "--chain", chain, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


# ──────────────────────────────────────────────────────────────
# Social — advanced
# ──────────────────────────────────────────────────────────────

@cached(ttl=300, prefix="surf")
async def get_social_detail(project: str) -> dict[str, Any] | None:
    result = await _run_surf("social-detail", "--project", project)
    data = _extract_data(result)
    return data if isinstance(data, dict) else None


@cached(ttl=300, prefix="surf")
async def get_social_engagement_score(handle: str) -> dict[str, Any] | None:
    result = await _run_surf("social-engagement-score", "--handle", handle)
    data = _extract_data(result)
    return data if isinstance(data, dict) else None


@cached(ttl=300, prefix="surf")
async def get_social_mindshare_timeseries(project: str, time_range: str = "7d") -> list[dict[str, Any]]:
    result = await _run_surf("social-mindshare", "--project", project, "--time-range", time_range)
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=300, prefix="surf")
async def get_social_smart_followers_history(handle: str, time_range: str = "30d") -> list[dict[str, Any]]:
    result = await _run_surf("social-smart-followers-history", "--handle", handle, "--time-range", time_range)
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=300, prefix="surf")
async def get_social_tweet_replies(tweet_id: str, limit: int = 20) -> list[dict[str, Any]]:
    result = await _run_surf("social-tweet-replies", "--tweet-id", tweet_id, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=300, prefix="surf")
async def get_social_tweets(tweet_ids: list[str]) -> list[dict[str, Any]]:
    ids_str = ",".join(tweet_ids)
    result = await _run_surf("social-tweets", "--ids", ids_str)
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=300, prefix="surf")
async def get_social_user_followers(handle: str, limit: int = 20) -> list[dict[str, Any]]:
    result = await _run_surf("social-user-followers", "--handle", handle, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=300, prefix="surf")
async def get_social_user_following(handle: str, limit: int = 20) -> list[dict[str, Any]]:
    result = await _run_surf("social-user-following", "--handle", handle, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=300, prefix="surf")
async def get_social_user_replies(handle: str, limit: int = 20) -> list[dict[str, Any]]:
    result = await _run_surf("social-user-replies", "--handle", handle, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


# ──────────────────────────────────────────────────────────────
# Project & Fund analysis
# ──────────────────────────────────────────────────────────────

@cached(ttl=300, prefix="surf")
async def get_project_detail(project: str) -> dict[str, Any] | None:
    result = await _run_surf("project-detail", "--project", project)
    data = _extract_data(result)
    return data if isinstance(data, dict) else None


@cached(ttl=300, prefix="surf")
async def get_project_pulse(project: str) -> dict[str, Any] | None:
    result = await _run_surf("project-pulse", "--project", project)
    data = _extract_data(result)
    return data if isinstance(data, dict) else None


@cached(ttl=300, prefix="surf")
async def get_project_defi_metrics(project: str) -> dict[str, Any] | None:
    result = await _run_surf("project-defi-metrics", "--project", project)
    data = _extract_data(result)
    return data if isinstance(data, dict) else None


@cached(ttl=300, prefix="surf")
async def get_project_defi_ranking(limit: int = 20, sort_by: str = "tvl") -> list[dict[str, Any]]:
    result = await _run_surf("project-defi-ranking", "--sort-by", sort_by, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=600, prefix="surf")
async def get_fund_detail(fund_id: str) -> dict[str, Any] | None:
    result = await _run_surf("fund-detail", "--fund-id", fund_id)
    data = _extract_data(result)
    return data if isinstance(data, dict) else None


@cached(ttl=600, prefix="surf")
async def get_fund_portfolio(fund_id: str) -> list[dict[str, Any]]:
    result = await _run_surf("fund-portfolio", "--fund-id", fund_id)
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=600, prefix="surf")
async def get_fund_ranking(limit: int = 20, sort_by: str = "aum") -> list[dict[str, Any]]:
    result = await _run_surf("fund-ranking", "--sort-by", sort_by, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


# ──────────────────────────────────────────────────────────────
# Search
# ──────────────────────────────────────────────────────────────

@cached(ttl=300, prefix="surf")
async def search_project(q: str, limit: int = 20) -> list[dict[str, Any]]:
    result = await _run_surf("search-project", "--q", q, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=300, prefix="surf")
async def search_airdrop(q: str = "", limit: int = 20) -> list[dict[str, Any]]:
    args = ["search-airdrop", "--limit", str(limit)]
    if q:
        args.extend(["--q", q])
    result = await _run_surf(*args)
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=300, prefix="surf")
async def search_airdrop_activities(project: str) -> list[dict[str, Any]]:
    result = await _run_surf("search-airdrop-activities", "--project", project)
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=300, prefix="surf")
async def search_events(q: str = "", limit: int = 20) -> list[dict[str, Any]]:
    args = ["search-events", "--limit", str(limit)]
    if q:
        args.extend(["--q", q])
    result = await _run_surf(*args)
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=300, prefix="surf")
async def search_fund(q: str, limit: int = 20) -> list[dict[str, Any]]:
    result = await _run_surf("search-fund", "--q", q, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=300, prefix="surf")
async def search_news(q: str, limit: int = 20) -> list[dict[str, Any]]:
    result = await _run_surf("search-news", "--q", q, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=300, prefix="surf")
async def search_prediction_market(q: str, limit: int = 20) -> list[dict[str, Any]]:
    result = await _run_surf("search-prediction-market", "--q", q, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=300, prefix="surf")
async def search_social_people(q: str, limit: int = 20) -> list[dict[str, Any]]:
    result = await _run_surf("search-social-people", "--q", q, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=300, prefix="surf")
async def search_social_posts(q: str, limit: int = 20) -> list[dict[str, Any]]:
    result = await _run_surf("search-social-posts", "--q", q, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


@cached(ttl=300, prefix="surf")
async def search_wallet(q: str, limit: int = 20) -> list[dict[str, Any]]:
    result = await _run_surf("search-wallet", "--q", q, "--limit", str(limit))
    data = _extract_data(result)
    return data if isinstance(data, list) else []


# ──────────────────────────────────────────────────────────────
# News advanced
# ──────────────────────────────────────────────────────────────

@cached(ttl=300, prefix="surf")
async def get_news_detail(article_id: str) -> dict[str, Any] | None:
    result = await _run_surf("news-detail", "--id", article_id)
    data = _extract_data(result)
    return data if isinstance(data, dict) else None
