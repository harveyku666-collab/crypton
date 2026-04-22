"""Fallback helpers for OKX Orbit-backed news and sentiment endpoints."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from sqlalchemy import desc, select

from app.common.database import async_session, db_available
from app.common.models import NewsItem
from app.news.token_matching import (
    build_search_terms,
    extract_symbols_from_text,
    item_matches_terms,
    term_matches_text,
)
from app.news.url_utils import normalize_news_source_url

LANGUAGE_MAP = {
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "zh-hans": "zh-CN",
    "en": "en-US",
    "en-us": "en-US",
}

TOKEN_STOPWORDS = {
    "AI",
    "APP",
    "API",
    "ATH",
    "CEX",
    "CPI",
    "CRYPTO",
    "DAO",
    "DEX",
    "ETF",
    "FED",
    "FOMC",
    "GPU",
    "IPO",
    "L2",
    "LONG",
    "MACD",
    "MARKET",
    "MEME",
    "NFT",
    "OI",
    "OKX",
    "PNL",
    "PPI",
    "RSI",
    "SEC",
    "SHORT",
    "USD",
    "USDC",
    "USDT",
}
FALLBACK_WARNING = "OKX Orbit 当前不可用，已回退到 BitInfo 站内新闻索引。"


def _normalize_language(language: str | None) -> str:
    key = str(language or "zh-CN").strip().lower().replace("_", "-")
    return LANGUAGE_MAP.get(key, "zh-CN" if key.startswith("zh") else "en-US")


def _language_variants(language: str | None) -> list[str]:
    normalized = _normalize_language(language)
    if normalized == "zh-CN":
        return ["zh-CN", "zh", "cn"]
    return ["en-US", "en"]


def _warning(reason: str | None = None) -> str:
    detail = str(reason or "").strip()
    return f"{FALLBACK_WARNING} 原因: {detail}" if detail else FALLBACK_WARNING


def _safe_timestamp_ms(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    raw = str(value).strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    try:
        return int(float(raw))
    except Exception:
        pass
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return int(parsed.timestamp() * 1000)
    except Exception:
        return None


def _normalize_importance(value: Any) -> str:
    raw = str(value or "").strip().lower()
    return "high" if raw in {"high", "important"} else "low"


def _article_text(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(key) or "")
        for key in ("title", "summary", "excerpt", "content")
    ).lower()


def _extract_symbols(title: str, content: str | None = None) -> list[str]:
    return extract_symbols_from_text(title, content, token_stopwords=TOKEN_STOPWORDS)


def _normalize_internal_news_item(item: NewsItem) -> dict[str, Any]:
    title = getattr(item, "title", "") or "Untitled"
    content = getattr(item, "content", None)
    excerpt = (content or title)[:280]
    published_at = _safe_timestamp_ms(getattr(item, "published_at", None))
    if published_at is None:
        created_at = getattr(item, "created_at", None)
        if created_at is not None:
            try:
                published_at = int(created_at.timestamp() * 1000)
            except Exception:
                published_at = None
    symbols = _extract_symbols(title, content)
    source = getattr(item, "source", None) or "internal"
    return {
        "id": getattr(item, "external_id", None) or getattr(item, "id", None),
        "external_id": getattr(item, "external_id", None),
        "title": title,
        "summary": excerpt or None,
        "excerpt": excerpt or None,
        "content": content,
        "source_url": normalize_news_source_url(getattr(item, "url", None), source=source),
        "platforms": [source],
        "coins": symbols,
        "importance": _normalize_importance(getattr(item, "importance", None)),
        "sentiment": getattr(item, "sentiment", "neutral") or "neutral",
        "published_at": published_at,
        "source": source,
        "language": getattr(item, "language", "") or "",
    }


async def _load_internal_items(language: str | None = None, *, limit: int = 240) -> list[dict[str, Any]]:
    if not db_available():
        return []
    async with async_session() as session:
        stmt = select(NewsItem).order_by(desc(NewsItem.created_at)).limit(limit)
        if language:
            stmt = stmt.where(NewsItem.language.in_(_language_variants(language)))
        rows = list((await session.execute(stmt)).scalars().all())
    return [_normalize_internal_news_item(row) for row in rows]


def _search_terms(*values: str | None) -> list[str]:
    return build_search_terms(*values)


def _match_score(item: dict[str, Any], terms: list[str]) -> int:
    if not terms:
        return 0
    text = _article_text(item)
    return sum(1 for term in terms if term and term_matches_text(text, term))


def _matches_terms(item: dict[str, Any], terms: list[str]) -> bool:
    return item_matches_terms(item, terms)


def _matches_platform(item: dict[str, Any], platform: str | None) -> bool:
    if not platform:
        return True
    target = platform.strip().lower()
    platforms = [str(value).strip().lower() for value in item.get("platforms") or []]
    return target in platforms


def _matches_time_window(item: dict[str, Any], begin: int | None, end: int | None) -> bool:
    ts = _safe_timestamp_ms(item.get("published_at"))
    if begin is not None and (ts is None or ts < begin):
        return False
    if end is not None and (ts is None or ts > end):
        return False
    return True


def _sentiment_distribution(items: list[dict[str, Any]]) -> dict[str, Any]:
    bullish = sum(1 for item in items if item.get("sentiment") == "bullish")
    bearish = sum(1 for item in items if item.get("sentiment") == "bearish")
    neutral = sum(1 for item in items if item.get("sentiment") == "neutral")
    total = bullish + bearish + neutral
    denominator = total or 1
    return {
        "bullish": bullish,
        "bearish": bearish,
        "neutral": neutral,
        "total": total,
        "bullish_ratio": bullish / denominator,
        "bearish_ratio": bearish / denominator,
        "neutral_ratio": neutral / denominator,
    }


def _build_trend(items: list[dict[str, Any]], trend_points: int | None) -> list[dict[str, Any]]:
    if not trend_points or trend_points <= 0 or not items:
        return []
    ordered = sorted(items, key=lambda item: _safe_timestamp_ms(item.get("published_at")) or 0, reverse=True)
    bucket_size = max(1, math.ceil(len(ordered) / trend_points))
    trend: list[dict[str, Any]] = []
    for start in range(0, len(ordered), bucket_size):
        bucket = ordered[start:start + bucket_size]
        if not bucket:
            continue
        distribution = _sentiment_distribution(bucket)
        trend.append({
            "ts": _safe_timestamp_ms(bucket[0].get("published_at")),
            "bullish_ratio": distribution["bullish_ratio"],
            "bearish_ratio": distribution["bearish_ratio"],
            "mention_count": distribution["total"],
        })
    return trend[:trend_points]


async def get_fallback_news_payload(
    *,
    kind: str,
    language: str = "zh-CN",
    limit: int = 10,
    coins: str | None = None,
    keyword: str | None = None,
    importance: str | None = None,
    platform: str | None = None,
    sentiment: str | None = None,
    begin: int | None = None,
    end: int | None = None,
    sort_by: str = "latest",
    reason: str | None = None,
) -> dict[str, Any]:
    items = await _load_internal_items(language)
    coin_terms = _search_terms(*(part.strip().upper() for part in str(coins or "").split(",") if part.strip()))
    keyword_terms = _search_terms(keyword)

    filtered: list[dict[str, Any]] = []
    for item in items:
        if importance and _normalize_importance(importance) != item.get("importance"):
            continue
        if sentiment and str(item.get("sentiment") or "").lower() != str(sentiment).strip().lower():
            continue
        if not _matches_platform(item, platform):
            continue
        if not _matches_time_window(item, begin, end):
            continue
        if coin_terms and not _matches_terms(item, coin_terms):
            continue
        if keyword_terms and not _matches_terms(item, keyword_terms):
            continue
        filtered.append(item)

    if sort_by == "relevant" and keyword_terms:
        filtered.sort(
            key=lambda item: (_match_score(item, keyword_terms + coin_terms), _safe_timestamp_ms(item.get("published_at")) or 0),
            reverse=True,
        )
    else:
        filtered.sort(key=lambda item: _safe_timestamp_ms(item.get("published_at")) or 0, reverse=True)

    limited = filtered[: min(max(limit, 1), 50)]
    return {
        "kind": kind,
        "language": _normalize_language(language),
        "items": limited,
        "count": len(limited),
        "next_cursor": None,
        "warning": _warning(reason),
    }


async def get_fallback_detail_payload(
    article_id: str,
    *,
    language: str = "zh-CN",
    reason: str | None = None,
) -> dict[str, Any]:
    items = await _load_internal_items(language, limit=320)
    resolved = next(
        (
            item for item in items
            if str(item.get("id")) == article_id
            or str(item.get("external_id")) == article_id
        ),
        None,
    )
    return {
        "item": resolved,
        "warning": _warning(reason) if resolved else None,
    }


async def get_fallback_platforms_payload(reason: str | None = None) -> dict[str, Any]:
    items = await _load_internal_items(None, limit=200)
    platforms = sorted({
        str(platform).strip()
        for item in items
        for platform in item.get("platforms") or []
        if str(platform).strip()
    })
    return {
        "items": platforms,
        "count": len(platforms),
        "warning": _warning(reason),
    }


async def get_fallback_coin_sentiment_payload(
    *,
    coins: str,
    period: str = "24h",
    trend_points: int | None = None,
    language: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    requested = [part.strip().upper() for part in str(coins or "").split(",") if part.strip()]
    items = await _load_internal_items(language)
    output: list[dict[str, Any]] = []

    for symbol in _dedupe(requested):
        terms = _search_terms(symbol)
        matched = [item for item in items if _matches_terms(item, terms)]
        if not matched:
            continue
        distribution = _sentiment_distribution(matched)
        if distribution["bullish_ratio"] > distribution["bearish_ratio"]:
            label = "bullish"
        elif distribution["bearish_ratio"] > distribution["bullish_ratio"]:
            label = "bearish"
        else:
            label = "neutral"
        output.append({
            "symbol": symbol,
            "label": label,
            "bullish_ratio": distribution["bullish_ratio"],
            "bearish_ratio": distribution["bearish_ratio"],
            "mention_count": distribution["total"],
            "trend": _build_trend(matched, trend_points),
        })

    return {
        "period": period,
        "items": output,
        "count": len(output),
        "warning": _warning(reason),
    }


async def get_fallback_sentiment_ranking_payload(
    *,
    period: str = "24h",
    sort_by: str = "hot",
    limit: int = 10,
    language: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    items = await _load_internal_items(language)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        for symbol in item.get("coins") or []:
            grouped.setdefault(str(symbol).upper(), []).append(item)

    ranking: list[dict[str, Any]] = []
    for symbol, rows in grouped.items():
        distribution = _sentiment_distribution(rows)
        if distribution["bullish_ratio"] > distribution["bearish_ratio"]:
            label = "bullish"
        elif distribution["bearish_ratio"] > distribution["bullish_ratio"]:
            label = "bearish"
        else:
            label = "neutral"
        ranking.append({
            "symbol": symbol,
            "label": label,
            "bullish_ratio": distribution["bullish_ratio"],
            "bearish_ratio": distribution["bearish_ratio"],
            "mention_count": distribution["total"],
            "trend": [],
        })

    if sort_by == "bullish":
        ranking.sort(key=lambda item: (item["bullish_ratio"], item["mention_count"]), reverse=True)
    elif sort_by == "bearish":
        ranking.sort(key=lambda item: (item["bearish_ratio"], item["mention_count"]), reverse=True)
    else:
        ranking.sort(key=lambda item: (item["mention_count"], item["bullish_ratio"]), reverse=True)

    limited = ranking[: min(max(limit, 1), 50)]
    return {
        "period": period,
        "sort_by": sort_by,
        "items": limited,
        "count": len(limited),
        "warning": _warning(reason),
    }
