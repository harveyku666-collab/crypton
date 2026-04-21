"""Market data API routes."""

from __future__ import annotations

from html import escape
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.market import aggregator
from app.common.http_client import fetch_bytes
from app.market.sources import (
    desk3,
    binance,
    binance_rank,
    coingecko,
    defi_llama,
    surf,
    gateio,
    bitget,
    okx,
    bybit,
)

router = APIRouter(prefix="/market", tags=["market"])


def _binance_icon_placeholder(label: str | None) -> bytes:
    raw = "".join(ch for ch in str(label or "?").upper() if ch.isalnum())[:4] or "?"
    safe = escape(raw)
    svg = f"""
    <svg xmlns="http://www.w3.org/2000/svg" width="72" height="72" viewBox="0 0 72 72">
      <defs>
        <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#20354a"/>
          <stop offset="100%" stop-color="#152536"/>
        </linearGradient>
      </defs>
      <rect width="72" height="72" rx="36" fill="url(#g)"/>
      <circle cx="36" cy="36" r="35" fill="none" stroke="rgba(255,255,255,0.08)"/>
      <text x="36" y="41" text-anchor="middle" font-family="Arial, sans-serif" font-size="22" font-weight="700" fill="#d9e7f4">{safe}</text>
    </svg>
    """.strip()
    return svg.encode("utf-8")


# ─── Exchange core (Surf) ──────────────────────────────────


@router.get("/exchange/depth")
async def exchange_depth(
    pair: str = Query("BTC/USDT"),
    exchange: str = Query("binance"),
    limit: int = Query(20, le=100),
) -> dict[str, Any]:
    symbol = pair.replace("/", "").replace("-", "").upper()
    result = await binance.get_order_book(symbol, limit)
    if result:
        return result
    result = await surf.get_exchange_depth(pair, exchange)
    return result or {"error": "No data"}


@router.get("/exchange/long-short-ratio")
async def exchange_long_short_ratio(
    pair: str = Query("BTC/USDT"),
    interval: str = Query("1h"),
    limit: int = Query(24, le=200),
) -> list[dict]:
    symbol = pair.replace("/", "").replace("-", "").upper()
    result = await binance.get_long_short_ratio(symbol, interval, limit)
    if result:
        return result
    return await surf.get_long_short_ratio(pair, interval, limit)


@router.get("/exchange/markets")
async def exchange_markets(
    exchange: str = Query("binance"),
    market_type: str = Query("spot"),
) -> list[dict]:
    return await surf.get_exchange_markets(exchange, market_type)


@router.get("/exchange/perp")
async def exchange_perp(
    symbol: str = Query("BTC"),
    sort_by: str = Query("open_interest"),
) -> list[dict]:
    return await surf.get_exchange_perp(symbol, sort_by)


@router.get("/exchange/price")
async def exchange_price(
    pair: str = Query("BTC/USDT"),
    exchange: str = Query("binance"),
) -> dict[str, Any]:
    result = await surf.get_exchange_price(pair, exchange)
    return result or {"error": "No data"}


# ─── Binance Web3 Market Rank ───────────────────────────────


@router.get("/binance/rank/icon")
async def binance_rank_icon(
    url: str | None = Query(None),
    symbol: str | None = Query(None),
) -> Response:
    normalized = binance_rank.normalize_static_asset_url(url)
    if not normalized or (urlparse(normalized).hostname or "") != "bin.bnbstatic.com":
        return Response(
            content=_binance_icon_placeholder(symbol),
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=3600"},
        )
    try:
        content, content_type = await fetch_bytes(
            normalized,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                "Referer": "https://web3.binance.com/",
            },
            retries=2,
        )
        return Response(
            content=content,
            media_type=content_type or "image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )
    except Exception:
        return Response(
            content=_binance_icon_placeholder(symbol),
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=3600"},
        )


@router.get("/binance/rank/social-hype")
async def binance_social_hype_rank(
    chain_id: str = Query("56"),
    sentiment: str = Query("All"),
    target_language: str = Query("zh"),
    time_range: int = Query(1, ge=1, le=7),
    social_language: str = Query("ALL"),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    try:
        return await binance_rank.get_social_hype_leaderboard(
            chain_id=chain_id,
            sentiment=sentiment,
            target_language=target_language,
            time_range=time_range,
            social_language=social_language,
            limit=limit,
        )
    except Exception as exc:
        return {
            "items": [],
            "count": 0,
            "error": str(exc),
            "filters": {
                "chain_id": chain_id,
                "sentiment": sentiment,
                "target_language": target_language,
                "time_range": time_range,
                "social_language": social_language,
            },
            "source": "binance_web3",
        }


@router.get("/binance/rank/unified")
async def binance_unified_rank(
    rank_type: int = Query(10),
    chain_id: str | None = Query(None),
    period: int = Query(50),
    sort_by: int = Query(0),
    order_asc: bool = Query(False),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    keywords: str | None = Query(None, description="Comma-separated symbols"),
    excludes: str | None = Query(None, description="Comma-separated symbols to exclude"),
    socials: str | None = Query(None, description="Comma-separated social filters"),
    alpha_tag_filter: str | None = Query(None, description="Comma-separated Alpha tags"),
    audit_filter: str | None = Query(None, description="Comma-separated audit flags"),
    tag_filter: str | None = Query(None, description="Comma-separated token tag ids"),
    percent_change_min: float | None = Query(None),
    percent_change_max: float | None = Query(None),
    market_cap_min: float | None = Query(None),
    market_cap_max: float | None = Query(None),
    volume_min: float | None = Query(None),
    volume_max: float | None = Query(None),
    liquidity_min: float | None = Query(None),
    liquidity_max: float | None = Query(None),
    holders_min: int | None = Query(None),
    holders_max: int | None = Query(None),
    holders_top10_percent_min: float | None = Query(None),
    holders_top10_percent_max: float | None = Query(None),
    kyc_holders_min: int | None = Query(None),
    kyc_holders_max: int | None = Query(None),
    count_min: int | None = Query(None),
    count_max: int | None = Query(None),
    unique_trader_min: int | None = Query(None),
    unique_trader_max: int | None = Query(None),
    launch_time_min: int | None = Query(None),
    launch_time_max: int | None = Query(None),
) -> dict[str, Any]:
    filters = binance_rank.build_unified_filters_from_strings(
        keywords=keywords,
        excludes=excludes,
        socials=socials,
        alpha_tag_filter=alpha_tag_filter,
        audit_filter=audit_filter,
        tag_filter=tag_filter,
        percent_change_min=percent_change_min,
        percent_change_max=percent_change_max,
        market_cap_min=market_cap_min,
        market_cap_max=market_cap_max,
        volume_min=volume_min,
        volume_max=volume_max,
        liquidity_min=liquidity_min,
        liquidity_max=liquidity_max,
        holders_min=holders_min,
        holders_max=holders_max,
        holders_top10_percent_min=holders_top10_percent_min,
        holders_top10_percent_max=holders_top10_percent_max,
        kyc_holders_min=kyc_holders_min,
        kyc_holders_max=kyc_holders_max,
        count_min=count_min,
        count_max=count_max,
        unique_trader_min=unique_trader_min,
        unique_trader_max=unique_trader_max,
        launch_time_min=launch_time_min,
        launch_time_max=launch_time_max,
    )
    try:
        return await binance_rank.get_unified_token_rank(
            rank_type=rank_type,
            chain_id=chain_id,
            period=period,
            sort_by=sort_by,
            order_asc=order_asc,
            page=page,
            size=size,
            filters=filters,
        )
    except Exception as exc:
        return {
            "items": [],
            "pagination": {
                "page": page,
                "size": size,
                "total": 0,
                "total_pages": 0,
                "has_prev": False,
                "has_next": False,
            },
            "error": str(exc),
            "filters": {
                "rank_type": rank_type,
                "chain_id": chain_id,
                "period": period,
                "sort_by": sort_by,
                "order_asc": order_asc,
            },
            "source": "binance_web3",
        }


@router.get("/binance/rank/smart-money")
async def binance_smart_money_rank(
    chain_id: str = Query("56"),
    period: str = Query("24h"),
    tag_type: int | None = Query(2),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    try:
        return await binance_rank.get_smart_money_inflow_rank(
            chain_id=chain_id,
            period=period,
            tag_type=tag_type,
            limit=limit,
        )
    except Exception as exc:
        return {
            "items": [],
            "count": 0,
            "error": str(exc),
            "filters": {
                "chain_id": chain_id,
                "period": period,
                "tag_type": tag_type,
            },
            "source": "binance_web3",
        }


@router.get("/binance/rank/meme")
async def binance_meme_rank(
    chain_id: str = Query("56"),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    try:
        return await binance_rank.get_meme_rank(chain_id=chain_id, limit=limit)
    except Exception as exc:
        return {
            "items": [],
            "count": 0,
            "error": str(exc),
            "filters": {
                "chain_id": chain_id,
            },
            "source": "binance_web3",
        }


@router.get("/binance/rank/address-pnl")
async def binance_address_pnl_rank(
    chain_id: str = Query("CT_501"),
    period: str = Query("30d"),
    tag: str = Query("ALL"),
    sort_by: int = Query(0),
    order_by: int = Query(0),
    page_no: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=25),
    pnl_min: float | None = Query(None),
    pnl_max: float | None = Query(None),
    win_rate_min: float | None = Query(None),
    win_rate_max: float | None = Query(None),
    tx_min: int | None = Query(None),
    tx_max: int | None = Query(None),
    volume_min: float | None = Query(None),
    volume_max: float | None = Query(None),
) -> dict[str, Any]:
    filters = binance_rank.build_pnl_filters(
        pnl_min=pnl_min,
        pnl_max=pnl_max,
        win_rate_min=win_rate_min,
        win_rate_max=win_rate_max,
        tx_min=tx_min,
        tx_max=tx_max,
        volume_min=volume_min,
        volume_max=volume_max,
    )
    try:
        return await binance_rank.get_address_pnl_rank(
            chain_id=chain_id,
            period=period,
            tag=tag,
            sort_by=sort_by,
            order_by=order_by,
            page_no=page_no,
            page_size=page_size,
            filters=filters,
        )
    except Exception as exc:
        return {
            "items": [],
            "pagination": {
                "page": page_no,
                "size": page_size,
                "total_pages": 0,
                "has_prev": False,
                "has_next": False,
            },
            "error": str(exc),
            "filters": {
                "chain_id": chain_id,
                "period": period,
                "tag": tag,
                "sort_by": sort_by,
                "order_by": order_by,
            },
            "source": "binance_web3",
        }


@router.get("/binance/rank/dashboard")
async def binance_rank_dashboard(
    chain_id: str = Query("56"),
    target_language: str = Query("zh"),
    social_sentiment: str = Query("All"),
    social_language: str = Query("ALL"),
    unified_rank_type: int = Query(10),
    unified_period: int = Query(50),
    unified_sort_by: int = Query(70),
    unified_order_asc: bool = Query(False),
    keyword: str | None = Query(None),
    unified_excludes: str | None = Query(None),
    unified_socials: str | None = Query(None),
    unified_alpha_tag_filter: str | None = Query(None),
    unified_audit_filter: str | None = Query(None),
    unified_tag_filter: str | None = Query(None),
    unified_percent_change_min: float | None = Query(None),
    unified_percent_change_max: float | None = Query(None),
    unified_market_cap_min: float | None = Query(None),
    unified_market_cap_max: float | None = Query(None),
    unified_volume_min: float | None = Query(None),
    unified_volume_max: float | None = Query(None),
    unified_liquidity_min: float | None = Query(None),
    unified_liquidity_max: float | None = Query(None),
    unified_holders_min: int | None = Query(None),
    unified_holders_max: int | None = Query(None),
    unified_holders_top10_percent_min: float | None = Query(None),
    unified_holders_top10_percent_max: float | None = Query(None),
    unified_kyc_holders_min: int | None = Query(None),
    unified_kyc_holders_max: int | None = Query(None),
    unified_count_min: int | None = Query(None),
    unified_count_max: int | None = Query(None),
    unified_unique_trader_min: int | None = Query(None),
    unified_unique_trader_max: int | None = Query(None),
    unified_launch_time_min: int | None = Query(None),
    unified_launch_time_max: int | None = Query(None),
    smart_money_chain_id: str = Query("56"),
    smart_money_period: str = Query("24h"),
    pnl_chain_id: str = Query("CT_501"),
    pnl_period: str = Query("30d"),
    pnl_tag: str = Query("ALL"),
    limit: int = Query(10, ge=3, le=25),
) -> dict[str, Any]:
    return await binance_rank.get_rank_dashboard(
        chain_id=chain_id,
        target_language=target_language,
        social_sentiment=social_sentiment,
        social_language=social_language,
        unified_rank_type=unified_rank_type,
        unified_period=unified_period,
        unified_sort_by=unified_sort_by,
        unified_order_asc=unified_order_asc,
        keyword=keyword,
        unified_excludes=unified_excludes,
        unified_socials=unified_socials,
        unified_alpha_tag_filter=unified_alpha_tag_filter,
        unified_audit_filter=unified_audit_filter,
        unified_tag_filter=unified_tag_filter,
        unified_percent_change_min=unified_percent_change_min,
        unified_percent_change_max=unified_percent_change_max,
        unified_market_cap_min=unified_market_cap_min,
        unified_market_cap_max=unified_market_cap_max,
        unified_volume_min=unified_volume_min,
        unified_volume_max=unified_volume_max,
        unified_liquidity_min=unified_liquidity_min,
        unified_liquidity_max=unified_liquidity_max,
        unified_holders_min=unified_holders_min,
        unified_holders_max=unified_holders_max,
        unified_holders_top10_percent_min=unified_holders_top10_percent_min,
        unified_holders_top10_percent_max=unified_holders_top10_percent_max,
        unified_kyc_holders_min=unified_kyc_holders_min,
        unified_kyc_holders_max=unified_kyc_holders_max,
        unified_count_min=unified_count_min,
        unified_count_max=unified_count_max,
        unified_unique_trader_min=unified_unique_trader_min,
        unified_unique_trader_max=unified_unique_trader_max,
        unified_launch_time_min=unified_launch_time_min,
        unified_launch_time_max=unified_launch_time_max,
        smart_money_chain_id=smart_money_chain_id,
        smart_money_period=smart_money_period,
        pnl_chain_id=pnl_chain_id,
        pnl_period=pnl_period,
        pnl_tag=pnl_tag,
        limit=limit,
    )


# ─── OKX Public Intelligence ────────────────────────────────


@router.get("/okx/ticker")
async def okx_ticker(
    inst_id: str = Query("BTC-USDT-SWAP"),
) -> dict[str, Any]:
    result = await okx.get_ticker(inst_id)
    return result or {"error": f"No OKX ticker data for {inst_id}"}


@router.get("/okx/tickers")
async def okx_tickers(
    inst_type: str = Query("SWAP"),
    uly: str | None = Query(None),
    inst_family: str | None = Query(None),
) -> list[dict[str, Any]]:
    return await okx.get_tickers(inst_type, uly, inst_family)


@router.get("/okx/index-ticker")
async def okx_index_ticker(
    inst_id: str | None = Query(None),
    quote_ccy: str | None = Query(None),
) -> list[dict[str, Any]]:
    return await okx.get_index_ticker(inst_id, quote_ccy)


@router.get("/okx/orderbook")
async def okx_orderbook(
    inst_id: str = Query("BTC-USDT-SWAP"),
    sz: int = Query(20, ge=1, le=400),
) -> dict[str, Any]:
    result = await okx.get_orderbook(inst_id, sz)
    return result or {"error": f"No OKX orderbook for {inst_id}"}


@router.get("/okx/candles")
async def okx_candles(
    inst_id: str = Query("BTC-USDT-SWAP"),
    bar: str = Query("1H"),
    after: str | None = Query(None),
    before: str | None = Query(None),
    limit: int = Query(100, ge=1, le=300),
) -> list[dict[str, Any]]:
    return await okx.get_candles(inst_id, bar, after, before, limit)


@router.get("/okx/index-candles")
async def okx_index_candles(
    inst_id: str = Query("BTC-USD"),
    bar: str = Query("1m"),
    after: str | None = Query(None),
    before: str | None = Query(None),
    limit: int = Query(100, ge=1, le=300),
    history: bool = Query(False),
) -> list[dict[str, Any]]:
    return await okx.get_index_candles(inst_id, bar, after, before, limit, history)


@router.get("/okx/instruments")
async def okx_instruments(
    inst_type: str = Query("SWAP"),
    inst_id: str | None = Query(None),
    uly: str | None = Query(None),
    inst_family: str | None = Query(None),
) -> Any:
    return await okx.get_instruments(inst_type, inst_id, uly, inst_family)


@router.get("/okx/funding-rate")
async def okx_funding_rate(
    inst_id: str = Query("BTC-USDT-SWAP"),
    history: bool = Query(False),
    after: str | None = Query(None),
    before: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
) -> Any:
    return await okx.get_funding_rate(
        inst_id,
        history=history,
        after=after,
        before=before,
        limit=limit,
    )


@router.get("/okx/mark-price")
async def okx_mark_price(
    inst_type: str = Query("SWAP"),
    inst_id: str | None = Query(None),
    uly: str | None = Query(None),
    inst_family: str | None = Query(None),
) -> Any:
    return await okx.get_mark_price(inst_type, inst_id, uly, inst_family)


@router.get("/okx/trades")
async def okx_trades(
    inst_id: str = Query("BTC-USDT-SWAP"),
    limit: int = Query(20, ge=1, le=500),
) -> list[dict[str, Any]]:
    return await okx.get_trades(inst_id, limit)


@router.get("/okx/price-limit")
async def okx_price_limit(
    inst_id: str = Query("BTC-USDT-SWAP"),
) -> dict[str, Any]:
    result = await okx.get_price_limit(inst_id)
    return result or {"error": f"No OKX price limit for {inst_id}"}


@router.get("/okx/open-interest")
async def okx_open_interest_public(
    inst_type: str = Query("SWAP"),
    inst_id: str | None = Query(None),
    uly: str | None = Query(None),
    inst_family: str | None = Query(None),
) -> Any:
    return await okx.get_public_open_interest(inst_type, inst_id, uly, inst_family)


@router.get("/okx/stock-tokens")
async def okx_stock_tokens(
    inst_type: str = Query("SWAP"),
    inst_id: str | None = Query(None),
) -> list[dict[str, Any]]:
    return await okx.get_stock_tokens(inst_type, inst_id)


@router.get("/okx/instruments-by-category")
async def okx_instruments_by_category(
    inst_category: str = Query(..., description="3=Stock, 4=Metals, 5=Commodities, 6=Forex, 7=Bonds"),
    inst_type: str = Query("SWAP"),
    inst_id: str | None = Query(None),
) -> list[dict[str, Any]]:
    return await okx.get_instruments_by_category(inst_category, inst_type, inst_id)


@router.get("/okx/filter")
async def okx_market_filter(
    inst_type: str = Query("SWAP"),
    base_ccy: str | None = Query(None),
    quote_ccy: str | None = Query(None),
    settle_ccy: str | None = Query(None),
    inst_family: str | None = Query(None),
    ct_type: str | None = Query(None),
    min_last: str | None = Query(None),
    max_last: str | None = Query(None),
    min_chg24h_pct: str | None = Query(None),
    max_chg24h_pct: str | None = Query(None),
    min_market_cap_usd: str | None = Query(None),
    max_market_cap_usd: str | None = Query(None),
    min_vol_usd_24h: str | None = Query(None),
    max_vol_usd_24h: str | None = Query(None),
    min_funding_rate: str | None = Query(None),
    max_funding_rate: str | None = Query(None),
    min_oi_usd: str | None = Query(None),
    max_oi_usd: str | None = Query(None),
    sort_by: str | None = Query(None),
    sort_order: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
) -> list[dict[str, Any]]:
    return await okx.market_filter(
        inst_type,
        base_ccy=base_ccy,
        quote_ccy=quote_ccy,
        settle_ccy=settle_ccy,
        inst_family=inst_family,
        ct_type=ct_type,
        min_last=min_last,
        max_last=max_last,
        min_chg24h_pct=min_chg24h_pct,
        max_chg24h_pct=max_chg24h_pct,
        min_market_cap_usd=min_market_cap_usd,
        max_market_cap_usd=max_market_cap_usd,
        min_vol_usd_24h=min_vol_usd_24h,
        max_vol_usd_24h=max_vol_usd_24h,
        min_funding_rate=min_funding_rate,
        max_funding_rate=max_funding_rate,
        min_oi_usd=min_oi_usd,
        max_oi_usd=max_oi_usd,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
    )


@router.get("/okx/oi-history")
async def okx_oi_history(
    inst_id: str = Query("BTC-USDT-SWAP"),
    bar: str = Query("1H"),
    limit: int = Query(50, ge=1, le=500),
    ts: int | None = Query(None),
) -> list[dict[str, Any]]:
    return await okx.get_oi_history(inst_id, bar=bar, limit=limit, ts=ts)


@router.get("/okx/oi-change")
async def okx_oi_change(
    inst_type: str = Query("SWAP"),
    bar: str = Query("1H"),
    min_oi_usd: str | None = Query(None),
    min_vol_usd_24h: str | None = Query(None),
    min_abs_oi_delta_pct: str | None = Query(None),
    sort_by: str | None = Query(None),
    sort_order: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
) -> list[dict[str, Any]]:
    return await okx.filter_oi_change(
        inst_type=inst_type,
        bar=bar,
        min_oi_usd=min_oi_usd,
        min_vol_usd_24h=min_vol_usd_24h,
        min_abs_oi_delta_pct=min_abs_oi_delta_pct,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
    )


# ─── Open Interest (OI) — free multi-exchange ────────────────


@router.get("/open-interest/{symbol}")
async def open_interest(
    symbol: str,
    limit: int = Query(24, le=100),
) -> dict[str, Any]:
    """Aggregated OI from multiple exchanges (Binance, Gate.io, Bitget).
    Binance requires PROXY_URL env var in geo-restricted regions.
    """
    import asyncio

    sym = symbol.upper()
    results = await asyncio.gather(
        binance.get_open_interest(f"{sym}USDT"),
        gateio.get_open_interest(sym),
        bitget.get_open_interest(sym),
        okx.get_open_interest(sym),
        bybit.get_open_interest(sym),
        binance.get_open_interest_history(f"{sym}USDT", limit=limit),
        gateio.get_open_interest_history(sym, limit=limit),
        okx.get_open_interest_history(sym, limit=limit),
        return_exceptions=True,
    )
    binance_cur, gate_cur, bitget_cur, okx_cur, bybit_cur = results[:5]
    binance_hist, gate_hist, okx_hist = results[5:]

    exchanges = []
    for result in [binance_cur, okx_cur, bybit_cur, gate_cur, bitget_cur]:
        if isinstance(result, dict):
            exchanges.append(result)

    history = []
    for hist in [binance_hist, okx_hist, gate_hist]:
        if isinstance(hist, list) and hist:
            history = hist
            break

    sources = []
    for name, result in [
        ("binance", binance_cur), ("okx", okx_cur), ("bybit", bybit_cur),
        ("gate.io", gate_cur), ("bitget", bitget_cur),
    ]:
        if isinstance(result, dict):
            sources.append(name)

    return {
        "symbol": sym,
        "current": exchanges,
        "history": history,
        "sources": sources if sources else ["gate.io", "bitget"],
    }


@router.get("/open-interest-history/{symbol}")
async def open_interest_history(
    symbol: str,
    limit: int = Query(48, le=100),
) -> list[dict]:
    """Historical OI + long/short + liquidation data from Gate.io."""
    return await gateio.get_open_interest_history(symbol.upper(), limit=limit)


# ─── ETF, Options, On-chain indicators ──────────────────────


@router.get("/etf")
async def etf_flows(
    symbol: str = Query("BTC"),
    limit: int = Query(30, le=100),
) -> list[dict]:
    return await surf.get_etf_flows(symbol, limit)


@router.get("/options")
async def options_data(symbol: str = Query("BTC")) -> Any:
    result = await surf.get_options(symbol)
    return result or {"error": "No data"}


@router.get("/onchain-indicator")
async def onchain_indicator(
    indicator: str = Query(..., description="e.g. nupl, sopr, mvrv, stock-to-flow"),
    symbol: str = Query("BTC"),
    limit: int = Query(30, le=200),
) -> list[dict]:
    return await surf.get_onchain_indicator(indicator, symbol, limit)


# ─── Events: listings, TGE, public sales ─────────────────────


@router.get("/events/listings")
async def listing_events(limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.get_listing_events(limit)


@router.get("/events/tge")
async def tge_events(limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.get_tge_events(limit)


@router.get("/events/public-sales")
async def public_sales(limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.get_public_sales(limit)


@router.get("/overview")
async def market_overview() -> dict[str, Any]:
    return await aggregator.get_market_overview()


@router.get("/price/{symbol}")
async def get_price(symbol: str) -> dict[str, Any]:
    result = await aggregator.get_symbol_price(symbol.upper())
    return result or {"error": f"No data for {symbol}"}


@router.get("/briefing")
async def full_briefing() -> dict[str, Any]:
    return await desk3.get_full_briefing()


@router.get("/fear-greed")
async def fear_greed() -> dict[str, Any]:
    desk3_fg = await desk3.get_fear_greed()
    gecko_fg = await coingecko.get_fear_greed()
    return {"desk3": desk3_fg, "coingecko": gecko_fg}


@router.get("/trending")
async def trending() -> dict[str, Any]:
    d3 = await desk3.get_trending(10)
    gecko = await coingecko.get_trending()
    return {"desk3": d3, "coingecko": gecko}


@router.get("/dominance")
async def dominance() -> dict[str, Any]:
    return await desk3.get_dominance() or {}


@router.get("/klines/{symbol}")
async def klines(
    symbol: str,
    interval: str = Query("15m"),
    limit: int = Query(50, le=1000),
) -> list:
    return await binance.get_klines(f"{symbol.upper()}USDT", interval, limit)


@router.get("/funding-rates")
async def funding_rates() -> list[dict]:
    return await binance.scan_funding_rates()


@router.get("/defi-yields")
async def defi_yields(
    min_apy: float = Query(1.0),
    min_tvl: float = Query(1_000_000),
    chain: str | None = Query(None),
    symbol: str | None = Query(None),
    limit: int = Query(50, le=200),
) -> list[dict]:
    return await defi_llama.scan_yields(min_apy, min_tvl, chain, symbol, limit)


@router.get("/cycles")
async def cycles() -> dict[str, Any]:
    return await desk3.get_cycles() or {}


@router.get("/cycle-indicators")
async def cycle_indicators() -> dict[str, Any]:
    return await desk3.get_cycle_indicators() or {}


@router.get("/calendar")
async def calendar(date: str | None = Query(None)) -> list[dict]:
    return await desk3.get_calendar(date)


# ─── Surf-powered endpoints ─────────────────────────────────


@router.get("/social/mindshare")
async def social_mindshare(
    limit: int = Query(10, le=50),
    time_range: str = Query("24h"),
) -> list[dict]:
    return await surf.get_social_mindshare_ranking(limit, time_range)


@router.get("/social/sentiment/{query}")
async def social_sentiment(query: str) -> dict[str, Any]:
    result = await surf.get_social_sentiment(query)
    return result or {"error": f"No sentiment data for {query}"}


@router.get("/social/user/{handle}")
async def social_user(handle: str) -> dict[str, Any]:
    result = await surf.get_social_user(handle)
    return result or {"error": f"No data for @{handle}"}


@router.get("/social/user/{handle}/posts")
async def social_user_posts(handle: str, limit: int = Query(10, le=50)) -> list[dict]:
    return await surf.get_social_user_posts(handle, limit)


@router.get("/liquidations/chart")
async def liquidation_chart(
    symbol: str = Query("BTC"),
    interval: str = Query("1h"),
    limit: int = Query(24, le=100),
) -> list[dict]:
    return await surf.get_liquidation_chart(symbol, interval, limit)


@router.get("/liquidations/exchanges")
async def liquidation_exchanges(
    symbol: str = Query("BTC"),
    time_range: str = Query("24h"),
) -> list[dict]:
    return await surf.get_liquidation_by_exchange(symbol, time_range)


@router.get("/liquidations/large-orders")
async def liquidation_large_orders(
    symbol: str | None = Query(None),
    limit: int = Query(20, le=100),
) -> list[dict]:
    return await surf.get_large_liquidations(symbol, limit)


@router.get("/funding-rates-multi")
async def funding_rates_multi() -> list[dict]:
    """Multi-exchange funding rates via Surf."""
    return await surf.get_funding_rates_multi()


# ─── Prediction markets (Surf) ──────────────────────────────


# ─── Prediction markets — Polymarket full suite ──────────────


@router.get("/prediction/polymarket")
async def polymarket_events(limit: int = Query(10, le=50)) -> list[dict]:
    from app.market.sources.polymarket import get_events
    return await get_events(limit)


@router.get("/prediction/polymarket/smart-money")
async def polymarket_smart_money(limit: int = Query(10, le=50), view: str = Query("overview")) -> list[dict]:
    return await surf.get_polymarket_smart_money(limit, view)


@router.get("/prediction/polymarket/leaderboard")
async def polymarket_leaderboard(limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.get_polymarket_leaderboard(limit)


@router.get("/prediction/polymarket/markets")
async def polymarket_markets(event_id: str | None = Query(None), limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.get_polymarket_markets(event_id, limit)


@router.get("/prediction/polymarket/open-interest/{market_id}")
async def polymarket_open_interest(market_id: str, interval: str = Query("1d"), limit: int = Query(30, le=100)) -> list[dict]:
    return await surf.get_polymarket_open_interest(market_id, interval, limit)


@router.get("/prediction/polymarket/orderbooks/{market_id}")
async def polymarket_orderbooks(market_id: str) -> dict[str, Any]:
    result = await surf.get_polymarket_orderbooks(market_id)
    return result or {"error": "No data"}


@router.get("/prediction/polymarket/positions/{address}")
async def polymarket_positions(address: str, limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.get_polymarket_positions(address, limit)


@router.get("/prediction/polymarket/ohlcv/{market_id}")
async def polymarket_ohlcv(market_id: str, interval: str = Query("1d"), limit: int = Query(30, le=100)) -> list[dict]:
    return await surf.get_polymarket_ohlcv(market_id, interval, limit)


@router.get("/prediction/polymarket/prices/{market_id}")
async def polymarket_prices(market_id: str, interval: str = Query("1h"), limit: int = Query(48, le=200)) -> list[dict]:
    return await surf.get_polymarket_prices(market_id, interval, limit)


@router.get("/prediction/polymarket/trades/{market_id}")
async def polymarket_trades(market_id: str, limit: int = Query(50, le=200)) -> list[dict]:
    return await surf.get_polymarket_trades(market_id, limit)


@router.get("/prediction/polymarket/volume-split/{market_id}")
async def polymarket_volume_split(market_id: str, interval: str = Query("1d"), limit: int = Query(30, le=100)) -> list[dict]:
    return await surf.get_polymarket_volume_split(market_id, interval, limit)


@router.get("/prediction/polymarket/volumes/{market_id}")
async def polymarket_volumes(market_id: str, interval: str = Query("1d"), limit: int = Query(30, le=100)) -> list[dict]:
    return await surf.get_polymarket_volumes(market_id, interval, limit)


# ─── Prediction markets — Kalshi full suite ──────────────────


@router.get("/prediction/kalshi/events")
async def kalshi_events(limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.get_kalshi_events(limit)


@router.get("/prediction/kalshi/markets")
async def kalshi_markets(event_id: str | None = Query(None), limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.get_kalshi_markets(event_id, limit)


@router.get("/prediction/kalshi/open-interest/{market_id}")
async def kalshi_open_interest(market_id: str, interval: str = Query("1d"), limit: int = Query(30, le=100)) -> list[dict]:
    return await surf.get_kalshi_open_interest(market_id, interval, limit)


@router.get("/prediction/kalshi/orderbooks/{market_id}")
async def kalshi_orderbooks(market_id: str) -> dict[str, Any]:
    result = await surf.get_kalshi_orderbooks(market_id)
    return result or {"error": "No data"}


@router.get("/prediction/kalshi/prices/{market_id}")
async def kalshi_prices(market_id: str, interval: str = Query("1h"), limit: int = Query(48, le=200)) -> list[dict]:
    return await surf.get_kalshi_prices(market_id, interval, limit)


@router.get("/prediction/kalshi/trades/{market_id}")
async def kalshi_trades(market_id: str, limit: int = Query(50, le=200)) -> list[dict]:
    return await surf.get_kalshi_trades(market_id, limit)


@router.get("/prediction/kalshi/volumes/{market_id}")
async def kalshi_volumes(market_id: str, interval: str = Query("1d"), limit: int = Query(30, le=100)) -> list[dict]:
    return await surf.get_kalshi_volumes(market_id, interval, limit)


# ─── Cross-platform prediction markets ───────────────────────


@router.get("/prediction/cross-platform/daily")
async def matching_market_daily() -> list[dict]:
    return await surf.get_matching_market_daily()


@router.get("/prediction/cross-platform/pairs")
async def matching_market_pairs(limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.get_matching_market_pairs(limit)


@router.get("/prediction/analytics")
async def prediction_analytics(limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.get_prediction_analytics(limit)


@router.get("/prediction/correlations")
async def prediction_correlations(limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.get_prediction_correlations(limit)


# ─── Token analysis ──────────────────────────────────────────


@router.get("/token/holders/{address}")
async def token_holders(address: str, chain: str = Query("ethereum"), limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.get_token_holders(address, chain, limit)


@router.get("/token/unlocks/{symbol}")
async def token_unlocks(symbol: str) -> list[dict]:
    return await surf.get_token_tokenomics(symbol)


@router.get("/token/dex-trades/{address}")
async def token_dex_trades(address: str, chain: str = Query("ethereum"), limit: int = Query(20, le=100)) -> list[dict]:
    from app.market.sources.dexscreener import get_token_pairs
    return await get_token_pairs(address, limit)


@router.get("/token/dex-trades-surf/{address}")
async def token_dex_trades_surf(address: str, chain: str = Query("ethereum"), limit: int = Query(50, le=200)) -> list[dict]:
    return await surf.get_token_dex_trades(address, chain, limit)


@router.get("/token/transfers/{address}")
async def token_transfers(address: str, chain: str = Query("ethereum"), limit: int = Query(50, le=200)) -> list[dict]:
    return await surf.get_token_transfers(address, chain, limit)


# ─── Social — advanced ───────────────────────────────────────


@router.get("/social/detail/{project}")
async def social_detail(project: str) -> dict[str, Any]:
    result = await surf.get_social_detail(project)
    return result or {"error": f"No data for {project}"}


@router.get("/social/engagement-score/{handle}")
async def social_engagement_score(handle: str) -> dict[str, Any]:
    result = await surf.get_social_engagement_score(handle)
    return result or {"error": f"No data for @{handle}"}


@router.get("/social/mindshare-ts/{project}")
async def social_mindshare_timeseries(project: str, time_range: str = Query("7d")) -> list[dict]:
    return await surf.get_social_mindshare_timeseries(project, time_range)


@router.get("/social/smart-followers/{handle}")
async def social_smart_followers_history(handle: str, time_range: str = Query("30d")) -> list[dict]:
    return await surf.get_social_smart_followers_history(handle, time_range)


@router.get("/social/tweet-replies/{tweet_id}")
async def social_tweet_replies(tweet_id: str, limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.get_social_tweet_replies(tweet_id, limit)


@router.get("/social/user/{handle}/followers")
async def social_user_followers(handle: str, limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.get_social_user_followers(handle, limit)


@router.get("/social/user/{handle}/following")
async def social_user_following(handle: str, limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.get_social_user_following(handle, limit)


@router.get("/social/user/{handle}/replies")
async def social_user_replies(handle: str, limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.get_social_user_replies(handle, limit)


# ─── Project & Fund analysis ─────────────────────────────────


@router.get("/project/detail/{project}")
async def project_detail(project: str) -> dict[str, Any]:
    result = await surf.get_project_detail(project)
    return result or {"error": f"No data for {project}"}


@router.get("/project/pulse/{project}")
async def project_pulse(project: str) -> dict[str, Any]:
    result = await surf.get_project_pulse(project)
    return result or {"error": f"No data for {project}"}


@router.get("/project/defi-metrics/{project}")
async def project_defi_metrics(project: str) -> dict[str, Any]:
    result = await surf.get_project_defi_metrics(project)
    return result or {"error": f"No data for {project}"}


@router.get("/project/defi-ranking")
async def project_defi_ranking(limit: int = Query(20, le=100), sort_by: str = Query("tvl")) -> list[dict]:
    return await surf.get_project_defi_ranking(limit, sort_by)


@router.get("/fund/detail/{fund_id}")
async def fund_detail(fund_id: str) -> dict[str, Any]:
    result = await surf.get_fund_detail(fund_id)
    return result or {"error": f"No data for {fund_id}"}


@router.get("/fund/portfolio/{fund_id}")
async def fund_portfolio(fund_id: str) -> list[dict]:
    return await surf.get_fund_portfolio(fund_id)


@router.get("/fund/ranking")
async def fund_ranking(limit: int = Query(20, le=100), sort_by: str = Query("aum")) -> list[dict]:
    return await surf.get_fund_ranking(limit, sort_by)


# ─── Search ───────────────────────────────────────────────────


@router.get("/search/project")
async def search_project(q: str = Query(...), limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.search_project(q, limit)


@router.get("/search/airdrop")
async def search_airdrop(q: str = Query(""), limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.search_airdrop(q, limit)


@router.get("/search/airdrop-activities/{project}")
async def search_airdrop_activities(project: str) -> list[dict]:
    return await surf.search_airdrop_activities(project)


@router.get("/search/events")
async def search_events(q: str = Query(""), limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.search_events(q, limit)


@router.get("/search/fund")
async def search_fund(q: str = Query(...), limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.search_fund(q, limit)


@router.get("/search/news")
async def search_news(q: str = Query(...), limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.search_news(q, limit)


@router.get("/search/prediction-market")
async def search_prediction_market(q: str = Query(...), limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.search_prediction_market(q, limit)


@router.get("/search/social/people")
async def search_social_people(q: str = Query(...), limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.search_social_people(q, limit)


@router.get("/search/social/posts")
async def search_social_posts(q: str = Query(...), limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.search_social_posts(q, limit)


@router.get("/search/wallet")
async def search_wallet(q: str = Query(...), limit: int = Query(20, le=100)) -> list[dict]:
    return await surf.search_wallet(q, limit)


# ─── OI Signal Engine ────────────────────────────────────

@router.get("/oi-signal/{symbol}")
async def oi_signal(
    symbol: str,
    timeframe: str = Query("1h"),
    chip_interval: str | None = Query(None),
) -> dict[str, Any]:
    """Multi-exchange OI signal scoring with 4-quadrant model."""
    from app.analysis.oi_signal import get_oi_signal
    return await get_oi_signal(
        symbol.upper(),
        timeframe=timeframe,
        chip_interval=chip_interval,
    )
