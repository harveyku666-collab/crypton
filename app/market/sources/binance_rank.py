"""Binance Web3 public leaderboards used by the crypto-market-rank skill."""

from __future__ import annotations

import asyncio
import json
from math import ceil
from typing import Any
from urllib.parse import urlparse

from app.common.cache import cached
from app.common.http_client import fetch_json, fetch_json_post

BASE = "https://web3.binance.com"
BN_STATIC = "https://bin.bnbstatic.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Encoding": "identity",
}
POST_HEADERS = {
    **HEADERS,
    "Content-Type": "application/json",
}

CHAIN_LABELS = {
    "1": "Ethereum",
    "56": "BSC",
    "8453": "Base",
    "CT_501": "Solana",
}

UNIFIED_PERIOD_FIELDS = {
    10: "1m",
    20: "5m",
    30: "1h",
    40: "4h",
    50: "24h",
}

UNIFIED_PERIOD_LABELS = {
    10: "1m",
    20: "5m",
    30: "1h",
    40: "4h",
    50: "24h",
}

RANK_TYPE_LABELS = {
    10: "Trending",
    11: "Top Search",
    20: "Alpha",
    40: "Stock",
}


def _prefix_logo(path: Any) -> str | None:
    if not path:
        return None
    value = str(path).strip()
    if not value:
        return None
    if value.startswith("//"):
        return f"https:{value}"
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("/"):
        return f"{BN_STATIC}{value}"
    return f"{BN_STATIC}/{value.lstrip('/')}"


def normalize_static_asset_url(value: Any) -> str | None:
    return _prefix_logo(value)


def is_binance_static_url(value: Any) -> bool:
    url = normalize_static_asset_url(value)
    if not url:
        return False
    return (urlparse(url).hostname or "") == "bin.bnbstatic.com"


def _to_float(value: Any) -> float | None:
    if value in (None, "", "null"):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value in (None, "", "null"):
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _parse_links(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return value
    if not value:
        return []
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


def _parse_csv(value: str | None, cast: type = str) -> list[Any] | None:
    if not value:
        return None
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        return None
    if cast is int:
        parsed: list[int] = []
        for item in items:
            try:
                parsed.append(int(item))
            except ValueError:
                continue
        return parsed or None
    return items


def _extract_tag_strings(value: Any) -> list[str]:
    found: list[str] = []

    def _walk(node: Any) -> None:
        if isinstance(node, str):
            text = node.strip()
            if text and text not in found:
                found.append(text)
            return
        if isinstance(node, list):
            for item in node:
                _walk(item)
            return
        if isinstance(node, dict):
            preferred = [
                "label", "name", "tagName", "displayName", "title",
                "tag", "narrative", "value", "desc", "description",
            ]
            for key in preferred:
                if key in node:
                    _walk(node.get(key))
            for item in node.values():
                if isinstance(item, (list, dict)):
                    _walk(item)

    _walk(value)
    cleaned: list[str] = []
    for item in found:
        normalized = item.strip()
        if len(normalized) <= 1:
            continue
        if normalized.lower() in {"true", "false", "null", "none"}:
            continue
        if normalized not in cleaned:
            cleaned.append(normalized)
    return cleaned[:6]


def _pick_period_metrics(token: dict[str, Any], period_field: str) -> dict[str, Any]:
    suffix = period_field
    price_change_key = f"percentChange{suffix}"
    volume_key = f"volume{suffix}"
    count_key = f"count{suffix}"
    unique_trader_key = f"uniqueTrader{suffix}"
    return {
        "period": suffix,
        "price_change_pct": _to_float(token.get(price_change_key)),
        "volume": _to_float(token.get(volume_key)),
        "volume_buy": _to_float(token.get(f"{volume_key}Buy")),
        "volume_sell": _to_float(token.get(f"{volume_key}Sell")),
        "count": _to_int(token.get(count_key)),
        "count_buy": _to_int(token.get(f"{count_key}Buy")),
        "count_sell": _to_int(token.get(f"{count_key}Sell")),
        "unique_traders": _to_int(token.get(unique_trader_key)),
    }


def _normalize_unified_token(token: dict[str, Any], period_field: str) -> dict[str, Any]:
    selected = _pick_period_metrics(token, period_field)
    alpha_info = token.get("alphaInfo") or {}
    audit_info = token.get("auditInfo") or {}
    token_tag = token.get("tokenTag") or {}
    tags = _extract_tag_strings([token_tag, alpha_info.get("tagList") or [], audit_info])
    return {
        "symbol": token.get("symbol"),
        "chain_id": str(token.get("chainId", "")),
        "chain_label": CHAIN_LABELS.get(str(token.get("chainId", "")), str(token.get("chainId", ""))),
        "contract_address": token.get("contractAddress"),
        "icon": _prefix_logo(token.get("icon")),
        "price": _to_float(token.get("price")),
        "market_cap": _to_float(token.get("marketCap")),
        "liquidity": _to_float(token.get("liquidity")),
        "holders": _to_int(token.get("holders")),
        "kyc_holders": _to_int(token.get("kycHolders")),
        "holders_top10_percent": _to_float(token.get("holdersTop10Percent")),
        "launch_time": _to_int(token.get("launchTime")),
        "price_change_pct": selected.get("price_change_pct"),
        "volume": selected.get("volume"),
        "volume_buy": selected.get("volume_buy"),
        "volume_sell": selected.get("volume_sell"),
        "count": selected.get("count"),
        "count_buy": selected.get("count_buy"),
        "count_sell": selected.get("count_sell"),
        "unique_traders": selected.get("unique_traders"),
        "selected_period": selected.get("period"),
        "price_change_24h_pct": _to_float(token.get("percentChange24h")),
        "volume_24h": _to_float(token.get("volume24h")),
        "count_24h": _to_int(token.get("count24h")),
        "unique_traders_24h": _to_int(token.get("uniqueTrader24h")),
        "links": _parse_links(token.get("links")),
        "alpha_info": alpha_info,
        "audit_info": audit_info,
        "token_tag": token_tag,
        "tags": tags,
    }


def _normalize_social_hype_item(item: dict[str, Any]) -> dict[str, Any]:
    meta = item.get("metaInfo") or {}
    market = item.get("marketInfo") or {}
    social = item.get("socialHypeInfo") or {}
    return {
        "symbol": meta.get("symbol"),
        "chain_id": str(meta.get("chainId", "")),
        "chain_label": CHAIN_LABELS.get(str(meta.get("chainId", "")), str(meta.get("chainId", ""))),
        "contract_address": meta.get("contractAddress"),
        "logo": _prefix_logo(meta.get("logo")),
        "token_age": _to_int(meta.get("tokenAge")),
        "market_cap": _to_float(market.get("marketCap")),
        "price_change_pct": _to_float(market.get("priceChange")),
        "social_hype": _to_float(social.get("socialHype")),
        "sentiment": social.get("sentiment"),
        "summary_brief": social.get("socialSummaryBriefTranslated") or social.get("socialSummaryBrief"),
        "summary_detail": social.get("socialSummaryDetailTranslated") or social.get("socialSummaryDetail"),
        "summary_brief_original": social.get("socialSummaryBrief"),
        "summary_detail_original": social.get("socialSummaryDetail"),
    }


def _normalize_smart_money_item(item: dict[str, Any]) -> dict[str, Any]:
    inflow = _to_float(item.get("inflow"))
    count_buy = _to_int(item.get("countBuy"))
    count_sell = _to_int(item.get("countSell"))
    buy_sell_ratio = None
    if count_buy is not None and count_sell not in (None, 0):
        buy_sell_ratio = round(count_buy / count_sell, 2)
    elif count_buy is not None and count_sell == 0:
        buy_sell_ratio = None
    tags = _extract_tag_strings(item.get("tokenTag") or {})
    return {
        "token_name": item.get("tokenName"),
        "symbol": item.get("tokenName"),
        "token_icon": _prefix_logo(item.get("tokenIconUrl")),
        "contract_address": item.get("ca"),
        "price": _to_float(item.get("price")),
        "market_cap": _to_float(item.get("marketCap")),
        "volume": _to_float(item.get("volume")),
        "price_change_pct": _to_float(item.get("priceChangeRate")),
        "liquidity": _to_float(item.get("liquidity")),
        "holders": _to_int(item.get("holders")),
        "kyc_holders": _to_int(item.get("kycHolders")),
        "holders_top10_percent": _to_float(item.get("holdersTop10Percent")),
        "count": _to_int(item.get("count")),
        "count_buy": count_buy,
        "count_sell": count_sell,
        "inflow": inflow,
        "traders": _to_int(item.get("traders")),
        "launch_time": _to_int(item.get("launchTime")),
        "token_decimals": _to_int(item.get("tokenDecimals")),
        "token_risk_level": _to_int(item.get("tokenRiskLevel")),
        "links": item.get("link") or [],
        "token_tag": item.get("tokenTag") or {},
        "tags": tags,
        "buy_sell_ratio": buy_sell_ratio,
        "flow_direction": "outflow" if inflow is not None and inflow < 0 else "inflow",
    }


def _normalize_meme_item(item: dict[str, Any]) -> dict[str, Any]:
    meta = item.get("metaInfo") or {}
    preview = item.get("previewLink") or {}
    token_tag = item.get("tokenTag") or {}
    tags = _extract_tag_strings(token_tag)
    if _to_int(meta.get("aiNarrativeFlag")):
        tags = ["AI 叙事", *[tag for tag in tags if tag != "AI Widget"]]
    return {
        "rank": _to_int(item.get("rank")),
        "score": _to_float(item.get("score")),
        "symbol": item.get("symbol"),
        "chain_id": str(item.get("chainId", "")),
        "chain_label": CHAIN_LABELS.get(str(item.get("chainId", "")), str(item.get("chainId", ""))),
        "contract_address": item.get("contractAddress"),
        "name": meta.get("name"),
        "icon": _prefix_logo(meta.get("icon")),
        "price": _to_float(item.get("price")),
        "percent_change_pct": _to_float(item.get("percentChange")),
        "percent_change_7d_pct": _to_float(item.get("percentChange7d")),
        "market_cap": _to_float(item.get("marketCap")),
        "liquidity": _to_float(item.get("liquidity")),
        "volume": _to_float(item.get("volume")),
        "volume_bn_total": _to_float(item.get("volumeBnTotal")),
        "volume_bn_7d": _to_float(item.get("volumeBn7d")),
        "holders": _to_int(item.get("holders")),
        "kyc_holders": _to_int(item.get("kycHolders")),
        "bn_unique_holders": _to_int(item.get("bnUniqueHolders")),
        "holders_top10_percent": _to_float(item.get("holdersTop10Percent")),
        "count": _to_int(item.get("count")),
        "count_bn_total": _to_int(item.get("countBnTotal")),
        "count_bn_7d": _to_int(item.get("countBn7d")),
        "unique_trader_bn": _to_int(item.get("uniqueTraderBn")),
        "unique_trader_bn_7d": _to_int(item.get("uniqueTraderBn7d")),
        "impression": _to_int(item.get("impression")),
        "create_time": _to_int(item.get("createTime")),
        "migrate_time": _to_int(item.get("migrateTime")),
        "alpha_status": _to_int(item.get("alphaStatus")),
        "ai_narrative_flag": _to_int(meta.get("aiNarrativeFlag")),
        "preview_link": preview,
        "token_tag": token_tag,
        "tags": tags[:6],
    }


def _normalize_top_earning_tokens(tokens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for token in tokens[:5]:
        result.append(
            {
                "token_address": token.get("tokenAddress"),
                "token_symbol": token.get("tokenSymbol"),
                "token_url": token.get("tokenUrl"),
                "realized_pnl": _to_float(token.get("realizedPnl")),
                "profit_rate": _to_float(token.get("profitRate")),
            }
        )
    return result


def _normalize_address_pnl_item(item: dict[str, Any]) -> dict[str, Any]:
    generic_tags = item.get("genericAddressTagList") or []
    return {
        "address": item.get("address"),
        "address_logo": item.get("addressLogo"),
        "address_label": item.get("addressLabel") or item.get("address"),
        "balance": _to_float(item.get("balance")),
        "tags": item.get("tags") or [],
        "realized_pnl": _to_float(item.get("realizedPnl")),
        "realized_pnl_percent": _to_float(item.get("realizedPnlPercent")),
        "daily_pnl": item.get("dailyPNL") or [],
        "win_rate": _to_float(item.get("winRate")),
        "total_volume": _to_float(item.get("totalVolume")),
        "buy_volume": _to_float(item.get("buyVolume")),
        "sell_volume": _to_float(item.get("sellVolume")),
        "avg_buy_volume": _to_float(item.get("avgBuyVolume")),
        "total_tx_cnt": _to_int(item.get("totalTxCnt")),
        "buy_tx_cnt": _to_int(item.get("buyTxCnt")),
        "sell_tx_cnt": _to_int(item.get("sellTxCnt")),
        "total_traded_tokens": _to_int(item.get("totalTradedTokens")),
        "top_earning_tokens": _normalize_top_earning_tokens(item.get("topEarningTokens") or []),
        "token_distribution": item.get("tokenDistribution") or {},
        "last_activity": _to_int(item.get("lastActivity")),
        "generic_address_tag_list": generic_tags,
        "trader_tags": _extract_tag_strings(generic_tags),
    }


def _build_unified_payload(
    *,
    rank_type: int,
    chain_id: str | None,
    period: int,
    sort_by: int,
    order_asc: bool,
    page: int,
    size: int,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "rankType": rank_type,
        "period": period,
        "sortBy": sort_by,
        "orderAsc": order_asc,
        "page": page,
        "size": size,
    }
    if chain_id:
        payload["chainId"] = chain_id
    for key, value in (filters or {}).items():
        if value not in (None, "", [], {}):
            payload[key] = value
    return payload


@cached(ttl=60, prefix="binance_rank")
async def get_social_hype_leaderboard(
    chain_id: str = "56",
    sentiment: str = "All",
    target_language: str = "zh",
    time_range: int = 1,
    social_language: str = "ALL",
    limit: int = 20,
) -> dict[str, Any]:
    data = await fetch_json(
        f"{BASE}/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/pulse/social/hype/rank/leaderboard",
        params={
            "chainId": chain_id,
            "sentiment": sentiment,
            "targetLanguage": target_language,
            "timeRange": time_range,
            "socialLanguage": social_language,
        },
        headers=HEADERS,
    )
    rows = (((data or {}).get("data") or {}).get("leaderBoardList") or [])[:limit]
    items = [_normalize_social_hype_item(item) for item in rows if isinstance(item, dict)]
    return {
        "items": items,
        "count": len(items),
        "filters": {
            "chain_id": chain_id,
            "chain_label": CHAIN_LABELS.get(chain_id, chain_id),
            "sentiment": sentiment,
            "target_language": target_language,
            "time_range": time_range,
            "social_language": social_language,
        },
        "source": "binance_web3",
    }


@cached(ttl=60, prefix="binance_rank")
async def get_unified_token_rank(
    rank_type: int = 10,
    chain_id: str | None = None,
    period: int = 50,
    sort_by: int = 0,
    order_asc: bool = False,
    page: int = 1,
    size: int = 20,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = _build_unified_payload(
        rank_type=rank_type,
        chain_id=chain_id,
        period=period,
        sort_by=sort_by,
        order_asc=order_asc,
        page=page,
        size=size,
        filters=filters,
    )
    data = await fetch_json_post(
        f"{BASE}/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/pulse/unified/rank/list",
        json_body=payload,
        headers=POST_HEADERS,
    )
    result = (data or {}).get("data") or {}
    rows = result.get("tokens") or []
    period_field = UNIFIED_PERIOD_FIELDS.get(period, "24h")
    items = [_normalize_unified_token(item, period_field) for item in rows if isinstance(item, dict)]
    total = _to_int(result.get("total")) or len(items)
    page_num = _to_int(result.get("page")) or page
    page_size = _to_int(result.get("size")) or size
    return {
        "items": items,
        "pagination": {
            "page": page_num,
            "size": page_size,
            "total": total,
            "total_pages": ceil(total / page_size) if page_size else 1,
            "has_prev": page_num > 1,
            "has_next": page_num * page_size < total,
        },
        "filters": {
            "rank_type": rank_type,
            "rank_type_label": RANK_TYPE_LABELS.get(rank_type, str(rank_type)),
            "chain_id": chain_id,
            "chain_label": CHAIN_LABELS.get(chain_id or "", chain_id) if chain_id else None,
            "period": period,
            "period_label": UNIFIED_PERIOD_LABELS.get(period, str(period)),
            "sort_by": sort_by,
            "order_asc": order_asc,
        },
        "source": "binance_web3",
    }


@cached(ttl=60, prefix="binance_rank")
async def get_smart_money_inflow_rank(
    chain_id: str = "56",
    period: str = "24h",
    tag_type: int | None = 2,
    limit: int = 20,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"chainId": chain_id, "period": period}
    if tag_type is not None:
        payload["tagType"] = tag_type
    data = await fetch_json_post(
        f"{BASE}/bapi/defi/v1/public/wallet-direct/tracker/wallet/token/inflow/rank/query",
        json_body=payload,
        headers=POST_HEADERS,
    )
    rows = ((data or {}).get("data") or [])[:limit]
    items = [
        {
            **_normalize_smart_money_item(item),
            "chain_id": chain_id,
            "chain_label": CHAIN_LABELS.get(chain_id, chain_id),
        }
        for item in rows
        if isinstance(item, dict)
    ]
    return {
        "items": items,
        "count": len(items),
        "filters": {
            "chain_id": chain_id,
            "chain_label": CHAIN_LABELS.get(chain_id, chain_id),
            "period": period,
            "tag_type": tag_type,
        },
        "source": "binance_web3",
    }


@cached(ttl=60, prefix="binance_rank")
async def get_meme_rank(
    chain_id: str = "56",
    limit: int = 20,
) -> dict[str, Any]:
    data = await fetch_json(
        f"{BASE}/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/pulse/exclusive/rank/list",
        params={"chainId": chain_id},
        headers=HEADERS,
    )
    rows = (((data or {}).get("data") or {}).get("tokens") or [])[:limit]
    items = [_normalize_meme_item(item) for item in rows if isinstance(item, dict)]
    return {
        "items": items,
        "count": len(items),
        "filters": {
            "chain_id": chain_id,
            "chain_label": CHAIN_LABELS.get(chain_id, chain_id),
        },
        "source": "binance_web3",
    }


@cached(ttl=60, prefix="binance_rank")
async def get_address_pnl_rank(
    chain_id: str = "CT_501",
    period: str = "30d",
    tag: str = "ALL",
    sort_by: int = 0,
    order_by: int = 0,
    page_no: int = 1,
    page_size: int = 20,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "chainId": chain_id,
        "period": period,
        "tag": tag,
        "sortBy": sort_by,
        "orderBy": order_by,
        "pageNo": page_no,
        "pageSize": page_size,
    }
    for key, value in (filters or {}).items():
        if value not in (None, ""):
            params[key] = value
    data = await fetch_json(
        f"{BASE}/bapi/defi/v1/public/wallet-direct/market/leaderboard/query",
        params=params,
        headers=HEADERS,
    )
    result = (data or {}).get("data") or {}
    rows = result.get("data") or []
    items = [
        {
            **_normalize_address_pnl_item(item),
            "chain_id": chain_id,
            "chain_label": CHAIN_LABELS.get(chain_id, chain_id),
        }
        for item in rows
        if isinstance(item, dict)
    ]
    current = _to_int(result.get("current")) or page_no
    size = _to_int(result.get("size")) or page_size
    total_pages = _to_int(result.get("pages")) or 1
    return {
        "items": items,
        "pagination": {
            "page": current,
            "size": size,
            "total_pages": total_pages,
            "has_prev": current > 1,
            "has_next": current < total_pages,
        },
        "filters": {
            "chain_id": chain_id,
            "chain_label": CHAIN_LABELS.get(chain_id, chain_id),
            "period": period,
            "tag": tag,
            "sort_by": sort_by,
            "order_by": order_by,
        },
        "source": "binance_web3",
    }


async def get_rank_dashboard(
    *,
    chain_id: str = "56",
    target_language: str = "zh",
    social_sentiment: str = "All",
    social_language: str = "ALL",
    unified_rank_type: int = 10,
    unified_period: int = 50,
    unified_sort_by: int = 70,
    unified_order_asc: bool = False,
    keyword: str | None = None,
    unified_excludes: str | None = None,
    unified_socials: str | None = None,
    unified_alpha_tag_filter: str | None = None,
    unified_audit_filter: str | None = None,
    unified_tag_filter: str | None = None,
    unified_percent_change_min: float | None = None,
    unified_percent_change_max: float | None = None,
    unified_market_cap_min: float | None = None,
    unified_market_cap_max: float | None = None,
    unified_volume_min: float | None = None,
    unified_volume_max: float | None = None,
    unified_liquidity_min: float | None = None,
    unified_liquidity_max: float | None = None,
    unified_holders_min: int | None = None,
    unified_holders_max: int | None = None,
    unified_holders_top10_percent_min: float | None = None,
    unified_holders_top10_percent_max: float | None = None,
    unified_kyc_holders_min: int | None = None,
    unified_kyc_holders_max: int | None = None,
    unified_count_min: int | None = None,
    unified_count_max: int | None = None,
    unified_unique_trader_min: int | None = None,
    unified_unique_trader_max: int | None = None,
    unified_launch_time_min: int | None = None,
    unified_launch_time_max: int | None = None,
    smart_money_chain_id: str = "56",
    smart_money_period: str = "24h",
    pnl_chain_id: str = "CT_501",
    pnl_period: str = "30d",
    pnl_tag: str = "ALL",
    limit: int = 10,
) -> dict[str, Any]:
    unified_filters = build_unified_filters_from_strings(
        keywords=keyword,
        excludes=unified_excludes,
        socials=unified_socials,
        alpha_tag_filter=unified_alpha_tag_filter,
        audit_filter=unified_audit_filter,
        tag_filter=unified_tag_filter,
        percent_change_min=unified_percent_change_min,
        percent_change_max=unified_percent_change_max,
        market_cap_min=unified_market_cap_min,
        market_cap_max=unified_market_cap_max,
        volume_min=unified_volume_min,
        volume_max=unified_volume_max,
        liquidity_min=unified_liquidity_min,
        liquidity_max=unified_liquidity_max,
        holders_min=unified_holders_min,
        holders_max=unified_holders_max,
        holders_top10_percent_min=unified_holders_top10_percent_min,
        holders_top10_percent_max=unified_holders_top10_percent_max,
        kyc_holders_min=unified_kyc_holders_min,
        kyc_holders_max=unified_kyc_holders_max,
        count_min=unified_count_min,
        count_max=unified_count_max,
        unique_trader_min=unified_unique_trader_min,
        unique_trader_max=unified_unique_trader_max,
        launch_time_min=unified_launch_time_min,
        launch_time_max=unified_launch_time_max,
    )

    async def _capture(fn: Any) -> dict[str, Any]:
        try:
            return await fn()
        except Exception as exc:  # pragma: no cover - network dependent
            return {"error": str(exc), "items": []}

    unified_task = _capture(
        lambda: get_unified_token_rank(
            rank_type=unified_rank_type,
            chain_id=chain_id,
            period=unified_period,
            sort_by=unified_sort_by,
            order_asc=unified_order_asc,
            page=1,
            size=limit,
            filters=unified_filters,
        )
    )
    social_task = _capture(
        lambda: get_social_hype_leaderboard(
            chain_id=chain_id,
            sentiment=social_sentiment,
            target_language=target_language,
            time_range=1,
            social_language=social_language,
            limit=limit,
        )
    )
    smart_money_bsc_task = _capture(
        lambda: get_smart_money_inflow_rank(
            chain_id="56",
            period=smart_money_period,
            tag_type=2,
            limit=limit,
        )
    )
    smart_money_solana_task = _capture(
        lambda: get_smart_money_inflow_rank(
            chain_id="CT_501",
            period=smart_money_period,
            tag_type=2,
            limit=limit,
        )
    )
    meme_task = _capture(lambda: get_meme_rank("56", limit))
    pnl_bsc_task = _capture(
        lambda: get_address_pnl_rank(
            chain_id="56",
            period=pnl_period,
            tag=pnl_tag,
            sort_by=0,
            order_by=0,
            page_no=1,
            page_size=min(limit, 25),
        )
    )
    pnl_solana_task = _capture(
        lambda: get_address_pnl_rank(
            chain_id="CT_501",
            period=pnl_period,
            tag=pnl_tag,
            sort_by=0,
            order_by=0,
            page_no=1,
            page_size=min(limit, 25),
        )
    )

    unified, social, smart_money_bsc, smart_money_solana, meme, pnl_bsc, pnl_solana = await asyncio.gather(
        unified_task,
        social_task,
        smart_money_bsc_task,
        smart_money_solana_task,
        meme_task,
        pnl_bsc_task,
        pnl_solana_task,
    )

    smart_money = _build_smart_money_dashboard(
        smart_money_bsc,
        smart_money_solana,
        period=smart_money_period,
        limit=limit,
    )
    pnl = _build_pnl_dashboard(
        pnl_bsc,
        pnl_solana,
        period=pnl_period,
        limit=limit,
    )

    summary = {
        "top_unified": (unified.get("items") or [None])[0],
        "top_social": (social.get("items") or [None])[0],
        "top_smart_money": smart_money.get("top"),
        "top_meme": (meme.get("items") or [None])[0],
        "top_trader": (pnl.get("items") or [None])[0],
    }

    return {
        "filters": {
            "chain_id": chain_id,
            "target_language": target_language,
            "social_sentiment": social_sentiment,
            "social_language": social_language,
            "unified_rank_type": unified_rank_type,
            "unified_period": unified_period,
            "unified_sort_by": unified_sort_by,
            "unified_order_asc": unified_order_asc,
            "keyword": keyword,
            "unified_excludes": unified_excludes,
            "unified_socials": unified_socials,
            "unified_alpha_tag_filter": unified_alpha_tag_filter,
            "unified_audit_filter": unified_audit_filter,
            "unified_tag_filter": unified_tag_filter,
            "unified_percent_change_min": unified_percent_change_min,
            "unified_percent_change_max": unified_percent_change_max,
            "unified_market_cap_min": unified_market_cap_min,
            "unified_market_cap_max": unified_market_cap_max,
            "unified_volume_min": unified_volume_min,
            "unified_volume_max": unified_volume_max,
            "unified_liquidity_min": unified_liquidity_min,
            "unified_liquidity_max": unified_liquidity_max,
            "unified_holders_min": unified_holders_min,
            "unified_holders_max": unified_holders_max,
            "unified_holders_top10_percent_min": unified_holders_top10_percent_min,
            "unified_holders_top10_percent_max": unified_holders_top10_percent_max,
            "unified_kyc_holders_min": unified_kyc_holders_min,
            "unified_kyc_holders_max": unified_kyc_holders_max,
            "unified_count_min": unified_count_min,
            "unified_count_max": unified_count_max,
            "unified_unique_trader_min": unified_unique_trader_min,
            "unified_unique_trader_max": unified_unique_trader_max,
            "unified_launch_time_min": unified_launch_time_min,
            "unified_launch_time_max": unified_launch_time_max,
            "smart_money_chain_id": smart_money_chain_id,
            "smart_money_period": smart_money_period,
            "pnl_chain_id": pnl_chain_id,
            "pnl_period": pnl_period,
            "pnl_tag": pnl_tag,
            "limit": limit,
        },
        "summary": summary,
        "sections": {
            "unified": unified,
            "social_hype": social,
            "smart_money": smart_money,
            "meme": meme,
            "address_pnl": pnl,
        },
        "source": "binance_web3",
    }


def _empty_smart_money_chain(chain_id: str, period: str, error: str | None = None) -> dict[str, Any]:
    return {
        "items": [],
        "count": 0,
        "filters": {
            "chain_id": chain_id,
            "chain_label": CHAIN_LABELS.get(chain_id, chain_id),
            "period": period,
            "tag_type": 2,
        },
        "source": "binance_web3",
        **({"error": error} if error else {}),
    }


def _empty_pnl_chain(chain_id: str, period: str, tag: str = "ALL", error: str | None = None) -> dict[str, Any]:
    return {
        "items": [],
        "pagination": {
            "page": 1,
            "size": 0,
            "total_pages": 1,
            "has_prev": False,
            "has_next": False,
        },
        "filters": {
            "chain_id": chain_id,
            "chain_label": CHAIN_LABELS.get(chain_id, chain_id),
            "period": period,
            "tag": tag,
            "sort_by": 0,
            "order_by": 0,
        },
        "source": "binance_web3",
        **({"error": error} if error else {}),
    }


def _build_smart_money_note(item: dict[str, Any]) -> str:
    parts: list[str] = []
    inflow = item.get("inflow")
    traders = item.get("traders")
    change = item.get("price_change_pct")
    ratio = item.get("buy_sell_ratio")
    tags = item.get("tags") or []
    if inflow is not None:
        parts.append(f"净流入 {inflow:.0f} 美元")
    if traders:
        parts.append(f"{traders} 个聪明钱地址参与")
    if change is not None and change < 0 and inflow is not None and inflow > 0:
        parts.append(f"24h 跌 {abs(change):.2f}% 但仍在被抄底")
    elif change is not None and change > 0 and inflow is not None and inflow > 0:
        parts.append(f"价格同步上涨 {change:.2f}%")
    if ratio and ratio >= 3:
        parts.append(f"买卖比约 {ratio}:1")
    if tags:
        parts.append(" / ".join(tags[:2]))
    return "，".join(parts) if parts else "值得继续观察"


def _build_smart_money_dashboard(
    bsc: dict[str, Any],
    solana: dict[str, Any],
    *,
    period: str,
    limit: int,
) -> dict[str, Any]:
    bsc_section = bsc if isinstance(bsc, dict) else _empty_smart_money_chain("56", period)
    sol_section = solana if isinstance(solana, dict) else _empty_smart_money_chain("CT_501", period)

    bsc_items = [item for item in (bsc_section.get("items") or []) if isinstance(item, dict)]
    sol_items = [item for item in (sol_section.get("items") or []) if isinstance(item, dict)]
    combined = [*bsc_items, *sol_items]

    positives = sorted(
        [item for item in combined if isinstance(item.get("inflow"), (int, float)) and item.get("inflow", 0) > 0],
        key=lambda item: float(item.get("inflow") or 0),
        reverse=True,
    )
    outflows = sorted(
        [item for item in combined if isinstance(item.get("inflow"), (int, float)) and item.get("inflow", 0) < 0],
        key=lambda item: float(item.get("inflow") or 0),
    )
    top = positives[0] if positives else (combined[0] if combined else None)

    highlights: list[dict[str, Any]] = []
    if positives:
        highlights.append(
            {
                "title": f"{positives[0].get('token_name') or positives[0].get('symbol')}",
                "reason": _build_smart_money_note(positives[0]),
            }
        )
    multi_trader = next((item for item in positives if (item.get("traders") or 0) >= 5 and item is not top), None)
    if multi_trader:
        highlights.append(
            {
                "title": f"{multi_trader.get('token_name') or multi_trader.get('symbol')}",
                "reason": _build_smart_money_note(multi_trader),
            }
        )
    strong_buyer = next(
        (
            item
            for item in positives
            if (item.get("buy_sell_ratio") or 0) >= 3
            and item is not top
            and item is not multi_trader
        ),
        None,
    )
    if strong_buyer:
        highlights.append(
            {
                "title": f"{strong_buyer.get('token_name') or strong_buyer.get('symbol')}",
                "reason": _build_smart_money_note(strong_buyer),
            }
        )
    if outflows:
        highlights.append(
            {
                "title": f"{outflows[0].get('token_name') or outflows[0].get('symbol')}",
                "reason": f"出现净流出 {abs(float(outflows[0].get('inflow') or 0)):.0f} 美元，可能有大户在撤退。",
            }
        )

    total_inflow = sum(float(item.get("inflow") or 0) for item in positives)
    total_outflow = sum(abs(float(item.get("inflow") or 0)) for item in outflows)
    error_messages = [msg for msg in [bsc_section.get("error"), sol_section.get("error")] if msg]
    return {
        "period": period,
        "limit": limit,
        "combined": combined,
        "top": top,
        "bsc": bsc_section,
        "solana": sol_section,
        "outflows": outflows[:limit],
        "highlights": highlights[:4],
        "metrics": {
            "total_inflow": total_inflow,
            "total_outflow": total_outflow,
            "positive_count": len(positives),
            "outflow_count": len(outflows),
        },
        **({"error": " / ".join(error_messages)} if error_messages and not combined else {}),
    }


def _build_pnl_note(item: dict[str, Any]) -> str:
    parts: list[str] = []
    pnl = item.get("realized_pnl")
    win_rate = item.get("win_rate")
    volume = item.get("total_volume")
    tags = item.get("trader_tags") or []
    top_tokens = item.get("top_earning_tokens") or []
    if pnl is not None:
        parts.append(f"区间实现盈亏 {pnl:.0f} 美元")
    if win_rate is not None:
        parts.append(f"胜率 {win_rate * 100:.1f}%")
    if volume is not None:
        parts.append(f"交易量 {volume:.0f} 美元")
    if top_tokens:
        top = top_tokens[0]
        symbol = top.get("token_symbol") or "头号盈利代币"
        realized = top.get("realized_pnl")
        if realized is not None:
            parts.append(f"{symbol} 贡献利润 {realized:.0f} 美元")
    if tags:
        parts.append(" / ".join(tags[:2]))
    return "，".join(parts) if parts else "值得继续跟踪"


def _build_pnl_dashboard(
    bsc: dict[str, Any],
    solana: dict[str, Any],
    *,
    period: str,
    limit: int,
) -> dict[str, Any]:
    bsc_section = bsc if isinstance(bsc, dict) else _empty_pnl_chain("56", period)
    sol_section = solana if isinstance(solana, dict) else _empty_pnl_chain("CT_501", period)

    bsc_items = [item for item in (bsc_section.get("items") or []) if isinstance(item, dict)]
    sol_items = [item for item in (sol_section.get("items") or []) if isinstance(item, dict)]
    combined = sorted(
        [*bsc_items, *sol_items],
        key=lambda item: float(item.get("realized_pnl") or 0),
        reverse=True,
    )
    top = combined[0] if combined else None
    steady = sorted(
        [
            item
            for item in combined
            if isinstance(item.get("win_rate"), (int, float))
            and isinstance(item.get("realized_pnl"), (int, float))
            and item.get("win_rate", 0) >= 0.55
            and item.get("realized_pnl", 0) > 0
        ],
        key=lambda item: ((item.get("win_rate") or 0), (item.get("realized_pnl") or 0)),
        reverse=True,
    )
    highlights: list[dict[str, Any]] = []
    if top:
        highlights.append(
            {
                "title": top.get("address_label") or top.get("address"),
                "reason": _build_pnl_note(top),
            }
        )
    steady_pick = next((item for item in steady if item is not top), None)
    if steady_pick:
        highlights.append(
            {
                "title": steady_pick.get("address_label") or steady_pick.get("address"),
                "reason": _build_pnl_note(steady_pick),
            }
        )
    concentrated = next(
        (
            item
            for item in combined
            if (item.get("top_earning_tokens") or [])
            and (item.get("total_traded_tokens") or 0) <= 20
            and item is not top
            and item is not steady_pick
        ),
        None,
    )
    if concentrated:
        highlights.append(
            {
                "title": concentrated.get("address_label") or concentrated.get("address"),
                "reason": _build_pnl_note(concentrated),
            }
        )

    error_messages = [msg for msg in [bsc_section.get("error"), sol_section.get("error")] if msg]
    return {
        "period": period,
        "limit": limit,
        "combined": combined,
        "top": top,
        "bsc": bsc_section,
        "solana": sol_section,
        "stable": steady[: min(limit, 6)],
        "highlights": highlights[:4],
        "metrics": {
            "combined_count": len(combined),
            "profitable_count": len([item for item in combined if (item.get("realized_pnl") or 0) > 0]),
            "best_pnl": float(top.get("realized_pnl") or 0) if top else 0.0,
        },
        **({"error": " / ".join(error_messages)} if error_messages and not combined else {}),
    }


def build_unified_filters_from_strings(
    *,
    keywords: str | None = None,
    excludes: str | None = None,
    socials: str | None = None,
    alpha_tag_filter: str | None = None,
    audit_filter: str | None = None,
    tag_filter: str | None = None,
    percent_change_min: float | None = None,
    percent_change_max: float | None = None,
    market_cap_min: float | None = None,
    market_cap_max: float | None = None,
    volume_min: float | None = None,
    volume_max: float | None = None,
    liquidity_min: float | None = None,
    liquidity_max: float | None = None,
    holders_min: int | None = None,
    holders_max: int | None = None,
    holders_top10_percent_min: float | None = None,
    holders_top10_percent_max: float | None = None,
    kyc_holders_min: int | None = None,
    kyc_holders_max: int | None = None,
    count_min: int | None = None,
    count_max: int | None = None,
    unique_trader_min: int | None = None,
    unique_trader_max: int | None = None,
    launch_time_min: int | None = None,
    launch_time_max: int | None = None,
) -> dict[str, Any]:
    filters: dict[str, Any] = {
        "keywords": _parse_csv(keywords, str),
        "excludes": _parse_csv(excludes, str),
        "socials": _parse_csv(socials, int),
        "alphaTagFilter": _parse_csv(alpha_tag_filter, str),
        "auditFilter": _parse_csv(audit_filter, int),
        "tagFilter": _parse_csv(tag_filter, int),
        "percentChangeMin": percent_change_min,
        "percentChangeMax": percent_change_max,
        "marketCapMin": market_cap_min,
        "marketCapMax": market_cap_max,
        "volumeMin": volume_min,
        "volumeMax": volume_max,
        "liquidityMin": liquidity_min,
        "liquidityMax": liquidity_max,
        "holdersMin": holders_min,
        "holdersMax": holders_max,
        "holdersTop10PercentMin": holders_top10_percent_min,
        "holdersTop10PercentMax": holders_top10_percent_max,
        "kycHoldersMin": kyc_holders_min,
        "kycHoldersMax": kyc_holders_max,
        "countMin": count_min,
        "countMax": count_max,
        "uniqueTraderMin": unique_trader_min,
        "uniqueTraderMax": unique_trader_max,
        "launchTimeMin": launch_time_min,
        "launchTimeMax": launch_time_max,
    }
    return {key: value for key, value in filters.items() if value not in (None, "", [], {})}


def build_pnl_filters(
    *,
    pnl_min: float | None = None,
    pnl_max: float | None = None,
    win_rate_min: float | None = None,
    win_rate_max: float | None = None,
    tx_min: int | None = None,
    tx_max: int | None = None,
    volume_min: float | None = None,
    volume_max: float | None = None,
) -> dict[str, Any]:
    filters = {
        "PNLMin": pnl_min,
        "PNLMax": pnl_max,
        "winRateMin": win_rate_min,
        "winRateMax": win_rate_max,
        "txMin": tx_min,
        "txMax": tx_max,
        "volumeMin": volume_min,
        "volumeMax": volume_max,
    }
    return {key: value for key, value in filters.items() if value is not None}
