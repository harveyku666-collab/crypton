"""OKX Orbit news and sentiment helpers.

These endpoints mirror the OKX CLI/MCP public intelligence layer for news,
article search, and coin sentiment. They intentionally avoid any trading
actions and only expose data that is useful for analysis pages.
"""

from __future__ import annotations

from typing import Any

from app.common.cache import cached
from app.common.http_client import fetch_json
from app.news.url_utils import normalize_news_source_url

BASE = "https://www.okx.com/api/v5/orbit"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
NEWS_IMPORTANCE = {"high", "low"}
NEWS_SENTIMENT = {"bullish", "bearish", "neutral"}
NEWS_SORT = {"latest", "relevant"}
SENTIMENT_PERIODS = {"1h", "4h", "24h"}
DETAIL_LEVELS = {"brief", "summary", "full"}


def _compact(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if v is not None and v != ""}


def _safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except Exception:
        return None


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _normalize_language(language: str | None) -> str:
    normalized = (language or "zh-CN").strip().lower().replace("_", "-")
    if normalized.startswith("zh"):
        return "zh-CN"
    return "en-US"


def _lang_headers(language: str | None) -> dict[str, str]:
    return {
        **HEADERS,
        "Accept-Language": _normalize_language(language),
    }


async def _orbit_get(
    path: str,
    params: dict[str, Any] | None = None,
    *,
    language: str | None = None,
) -> Any:
    return await fetch_json(
        f"{BASE}{path}",
        params=params,
        headers=_lang_headers(language),
    )


def _unwrap_page(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    rows = data.get("data")
    if not isinstance(rows, list) or not rows:
        return {}
    page = rows[0]
    return page if isinstance(page, dict) else {}


def _response_status(data: Any) -> tuple[Any, Any, str | None]:
    code = None
    msg = None
    if isinstance(data, dict):
        code = data.get("code")
        msg = data.get("msg")

    warning = None
    if code not in {"0", 0, None}:
        warning = f"OKX Orbit API returned code {code}"
        if str(code) == "50026":
            warning = "OKX Orbit is currently app-only; the public web Orbit API is unavailable"
    return code, msg, warning


def _normalize_article(item: dict[str, Any]) -> dict[str, Any]:
    raw_content = str(item.get("content") or "")
    summary = str(item.get("summary") or "").strip()
    excerpt = summary or raw_content[:280]
    return {
        "id": item.get("id"),
        "title": item.get("title", ""),
        "summary": summary or None,
        "excerpt": excerpt or None,
        "content": raw_content or None,
        "source_url": normalize_news_source_url(item.get("sourceUrl"), source="okx_orbit"),
        "platforms": item.get("platformList") if isinstance(item.get("platformList"), list) else [],
        "coins": item.get("ccyList") if isinstance(item.get("ccyList"), list) else [],
        "importance": item.get("importance"),
        "sentiment": item.get("sentiment"),
        "published_at": _safe_int(item.get("cTime") or item.get("createTime")),
        "source": "okx_orbit",
    }


def _normalize_news_page(
    data: Any,
    *,
    language: str,
    limit: int,
    kind: str,
) -> dict[str, Any]:
    code, msg, warning = _response_status(data)
    page = _unwrap_page(data)
    details = page.get("details") if isinstance(page.get("details"), list) else []
    return {
        "kind": kind,
        "language": _normalize_language(language),
        "items": [_normalize_article(item) for item in details if isinstance(item, dict)],
        "count": len(details),
        "next_cursor": page.get("nextCursor"),
        "warning": warning,
        "code": code,
        "msg": msg,
    }


def _normalize_sentiment_item(item: dict[str, Any]) -> dict[str, Any]:
    sentiment = item.get("sentiment") if isinstance(item.get("sentiment"), dict) else {}
    trend = item.get("trend") if isinstance(item.get("trend"), list) else []
    return {
        "symbol": item.get("ccy"),
        "label": sentiment.get("label"),
        "bullish_ratio": _safe_float(sentiment.get("bullishRatio")),
        "bearish_ratio": _safe_float(sentiment.get("bearishRatio")),
        "mention_count": _safe_int(item.get("mentionCnt")),
        "trend": [
            {
                "ts": _safe_int(point.get("ts")) if isinstance(point, dict) else None,
                "bullish_ratio": _safe_float(point.get("bullishRatio")) if isinstance(point, dict) else None,
                "bearish_ratio": _safe_float(point.get("bearishRatio")) if isinstance(point, dict) else None,
                "mention_count": _safe_int(point.get("mentionCnt")) if isinstance(point, dict) else None,
            }
            for point in trend
            if isinstance(point, dict)
        ],
    }


@cached(ttl=90, prefix="okx_news_latest")
async def get_latest_news(
    *,
    coins: str | None = None,
    importance: str | None = None,
    platform: str | None = None,
    begin: int | None = None,
    end: int | None = None,
    language: str = "zh-CN",
    detail_lvl: str = "summary",
    limit: int = 10,
    after: str | None = None,
) -> dict[str, Any]:
    resolved_importance = importance if importance in NEWS_IMPORTANCE else None
    resolved_detail = detail_lvl if detail_lvl in DETAIL_LEVELS else "summary"
    data = await _orbit_get(
        "/news-search",
        _compact({
            "sortBy": "latest",
            "importance": resolved_importance,
            "platform": platform,
            "ccyList": coins,
            "begin": begin,
            "end": end,
            "detailLvl": resolved_detail,
            "limit": min(max(limit, 1), 50),
            "cursor": after,
        }),
        language=language,
    )
    return _normalize_news_page(data, language=language, limit=limit, kind="latest")


@cached(ttl=90, prefix="okx_news_coin")
async def get_news_by_coin(
    *,
    coins: str,
    importance: str | None = None,
    platform: str | None = None,
    begin: int | None = None,
    end: int | None = None,
    language: str = "zh-CN",
    detail_lvl: str = "summary",
    limit: int = 10,
) -> dict[str, Any]:
    resolved_importance = importance if importance in NEWS_IMPORTANCE else None
    resolved_detail = detail_lvl if detail_lvl in DETAIL_LEVELS else "summary"
    data = await _orbit_get(
        "/news-search",
        _compact({
            "sortBy": "latest",
            "ccyList": coins.upper(),
            "importance": resolved_importance,
            "platform": platform,
            "begin": begin,
            "end": end,
            "detailLvl": resolved_detail,
            "limit": min(max(limit, 1), 50),
        }),
        language=language,
    )
    return _normalize_news_page(data, language=language, limit=limit, kind="coin")


@cached(ttl=90, prefix="okx_news_search")
async def search_news(
    *,
    keyword: str | None = None,
    coins: str | None = None,
    importance: str | None = None,
    platform: str | None = None,
    sentiment: str | None = None,
    sort_by: str = "relevant",
    begin: int | None = None,
    end: int | None = None,
    language: str = "zh-CN",
    detail_lvl: str = "summary",
    limit: int = 10,
    after: str | None = None,
) -> dict[str, Any]:
    resolved_importance = importance if importance in NEWS_IMPORTANCE else None
    resolved_sentiment = sentiment if sentiment in NEWS_SENTIMENT else None
    resolved_sort = sort_by if sort_by in NEWS_SORT else "relevant"
    resolved_detail = detail_lvl if detail_lvl in DETAIL_LEVELS else "summary"
    data = await _orbit_get(
        "/news-search",
        _compact({
            "keyword": keyword,
            "sortBy": resolved_sort,
            "importance": resolved_importance,
            "platform": platform,
            "ccyList": coins.upper() if isinstance(coins, str) and coins else None,
            "sentiment": resolved_sentiment,
            "begin": begin,
            "end": end,
            "detailLvl": resolved_detail,
            "limit": min(max(limit, 1), 50),
            "cursor": after,
        }),
        language=language,
    )
    return _normalize_news_page(data, language=language, limit=limit, kind="search")


@cached(ttl=300, prefix="okx_news_detail")
async def get_news_detail(
    article_id: str,
    *,
    language: str = "zh-CN",
) -> dict[str, Any]:
    data = await _orbit_get("/news-detail", {"id": article_id}, language=language)
    code, msg, warning = _response_status(data)
    page = _unwrap_page(data)
    details = page.get("details") if isinstance(page.get("details"), list) else None
    if isinstance(details, list) and details and isinstance(details[0], dict):
        article = details[0]
    else:
        rows = data.get("data") if isinstance(data, dict) else None
        article = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None
    return {
        "item": _normalize_article(article) if isinstance(article, dict) else None,
        "code": code,
        "msg": msg,
        "warning": warning,
    }


@cached(ttl=1800, prefix="okx_news_platforms")
async def get_news_platforms() -> dict[str, Any]:
    data = await _orbit_get("/news-platform")
    code, msg, warning = _response_status(data)
    page = _unwrap_page(data)
    platforms = page.get("platform") if isinstance(page.get("platform"), list) else []
    return {
        "items": [str(item) for item in platforms if item],
        "count": len(platforms),
        "code": code,
        "msg": msg,
        "warning": warning,
    }


@cached(ttl=300, prefix="okx_news_sentiment_coin")
async def get_coin_sentiment(
    *,
    coins: str,
    period: str = "24h",
    trend_points: int | None = None,
) -> dict[str, Any]:
    resolved_period = period if period in SENTIMENT_PERIODS else "24h"
    include_trend = isinstance(trend_points, int) and trend_points > 0
    data = await _orbit_get(
        "/currency-sentiment-query",
        _compact({
            "ccy": coins.upper(),
            "period": "1h" if include_trend and resolved_period == "24h" else resolved_period,
            "inclTrend": True if include_trend else None,
            "limit": min(max(trend_points or 0, 1), 48) if include_trend else None,
        }),
    )
    code, msg, warning = _response_status(data)
    page = _unwrap_page(data)
    details = page.get("details") if isinstance(page.get("details"), list) else []
    return {
        "period": resolved_period,
        "items": [_normalize_sentiment_item(item) for item in details if isinstance(item, dict)],
        "count": len(details),
        "code": code,
        "msg": msg,
        "warning": warning,
    }


@cached(ttl=300, prefix="okx_news_sentiment_rank")
async def get_sentiment_ranking(
    *,
    period: str = "24h",
    sort_by: str = "hot",
    limit: int = 10,
) -> dict[str, Any]:
    resolved_period = period if period in SENTIMENT_PERIODS else "24h"
    resolved_sort = sort_by if sort_by in {"hot", "bullish", "bearish"} else "hot"
    data = await _orbit_get(
        "/currency-sentiment-ranking",
        {
            "period": resolved_period,
            "sortBy": resolved_sort,
            "limit": min(max(limit, 1), 50),
        },
    )
    code, msg, warning = _response_status(data)
    page = _unwrap_page(data)
    details = page.get("details") if isinstance(page.get("details"), list) else []
    return {
        "period": resolved_period,
        "sort_by": resolved_sort,
        "items": [_normalize_sentiment_item(item) for item in details if isinstance(item, dict)],
        "count": len(details),
        "code": code,
        "msg": msg,
        "warning": warning,
    }
