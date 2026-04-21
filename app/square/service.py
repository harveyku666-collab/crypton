"""Square module service layer."""

from __future__ import annotations

import asyncio
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import BigInteger, and_, cast, desc, func, or_, select

from app.common.cache import cached
from app.common.database import async_session, db_available
from app.common.http_client import fetch_json
from app.common.models import SquareCollectionState, SquareHotTokenSnapshot, SquareItem, SquareKOLProfile
from app.config import settings
from app.market.sources.okx import get_instruments as get_okx_instruments
from app.square.sources.binance import get_square_content as get_binance_square_content
from app.square.sources.okx import get_square_content as get_okx_square_content

SQUARE_PLATFORMS = ("binance", "okx")
SQUARE_ITEM_TYPES = ("post", "topic", "article")
TOKEN_RE = re.compile(r"[$#]([A-Za-z][A-Za-z0-9]{1,14})")
DEFAULT_COLLECT_FRONTFILL_PAGES = 2
TOKEN_ALIAS_MAP = {
    "BITCOIN": "BTC",
    "ETHEREUM": "ETH",
    "SOLANA": "SOL",
    "BINANCECOIN": "BNB",
    "RIPPLE": "XRP",
    "DOGECOIN": "DOGE",
    "CARDANO": "ADA",
    "CHAINLINK": "LINK",
    "ARBITRUM": "ARB",
    "POLYGON": "POL",
    "WORLDCOIN": "WLD",
    "RENDER": "RENDER",
}
TOKEN_STOPWORDS = {
    "CRYPTO",
    "CRYPTOS",
    "MARKET",
    "MARKETS",
    "TRADING",
    "TRADER",
    "TRADERS",
    "FUTURE",
    "FUTURES",
    "FUTUREEVENTS",
    "FUTURETRADERS",
    "SIGNAL",
    "SIGNALS",
    "LONG",
    "SHORT",
    "BULLISH",
    "BEARISH",
    "ALTCOIN",
    "ALTCOINS",
    "MEMECOIN",
    "MEMECOINS",
    "BITCOINAMSTERDAM",
    "DYOR",
}
MAX_UNVERIFIED_TOKEN_LENGTH = 10

SQUARE_SOURCE_FETCHERS = {
    "binance": get_binance_square_content,
    "okx": get_okx_square_content,
}


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@cached(ttl=21600, prefix="square_tradable_symbols")
async def load_tradable_symbols() -> list[str]:
    symbols: set[str] = set()
    try:
        data = await fetch_json("https://api.binance.com/api/v3/exchangeInfo")
        if isinstance(data, dict) and isinstance(data.get("symbols"), list):
            for row in data.get("symbols", []):
                if not isinstance(row, dict):
                    continue
                if str(row.get("status") or "").upper() != "TRADING":
                    continue
                base_asset = normalize_token_candidate(row.get("baseAsset"))
                if base_asset and base_asset not in TOKEN_STOPWORDS:
                    symbols.add(base_asset)
    except Exception:
        pass

    try:
        rows = await get_okx_instruments("SPOT")
        if isinstance(rows, dict):
            rows = [rows]
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                base_ccy = normalize_token_candidate(row.get("baseCcy"))
                if not base_ccy:
                    inst_id = str(row.get("instId") or "")
                    if "-" in inst_id:
                        base_ccy = normalize_token_candidate(inst_id.split("-", 1)[0])
                if base_ccy and base_ccy not in TOKEN_STOPWORDS:
                    symbols.add(base_ccy)
    except Exception:
        pass

    return sorted(symbols)


def normalize_platforms(platforms: list[str] | tuple[str, ...] | None = None) -> list[str]:
    if not platforms:
        return list(SQUARE_PLATFORMS)
    seen: set[str] = set()
    output: list[str] = []
    for platform in platforms:
        normalized = str(platform).strip().lower()
        if normalized in SQUARE_PLATFORMS and normalized not in seen:
            seen.add(normalized)
            output.append(normalized)
    return output or list(SQUARE_PLATFORMS)


def normalize_language(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower().replace("_", "-")
    return normalized or None


def normalize_identity(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).strip().split()).lower()
    normalized = normalized.lstrip("@")
    return normalized or None


def build_author_key(
    *,
    platform: str,
    author_id: str | None,
    author_handle: str | None,
    author_name: str | None,
) -> str | None:
    if normalize_identity(author_id):
        return f"{platform}:id:{normalize_identity(author_id)}"
    if normalize_identity(author_handle):
        return f"{platform}:handle:{normalize_identity(author_handle)}"
    if normalize_identity(author_name):
        return f"{platform}:name:{normalize_identity(author_name)}"
    return None


def normalize_token_candidate(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip().upper().lstrip("$#").strip()
    if not cleaned:
        return None
    return TOKEN_ALIAS_MAP.get(cleaned, cleaned)


def filter_token_candidates(
    candidates: list[Any],
    *,
    tradable_symbols: set[str] | None = None,
) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = normalize_token_candidate(candidate)
        if not normalized:
            continue
        if normalized in TOKEN_STOPWORDS:
            continue
        if tradable_symbols is None and len(normalized) > MAX_UNVERIFIED_TOKEN_LENGTH and normalized.isalpha():
            continue
        if tradable_symbols is not None and normalized not in tradable_symbols:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output


def parse_timestamp_ms(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        ts = int(float(value))
    except Exception:
        return None
    if abs(ts) < 10**12:
        return ts * 1000
    return ts


def _square_published_at_expr():
    return cast(func.nullif(SquareItem.published_at, ""), BigInteger)


def _row_effective_timestamp_ms(item: SquareItem | dict[str, Any]) -> int | None:
    if isinstance(item, dict):
        published_at = parse_timestamp_ms(item.get("published_at"))
        if published_at is not None:
            return published_at
        created_at = item.get("stored_at") or item.get("created_at")
    else:
        published_at = parse_timestamp_ms(getattr(item, "published_at", None))
        if published_at is not None:
            return published_at
        created_at = getattr(item, "created_at", None)
    if isinstance(created_at, datetime):
        return int(created_at.timestamp() * 1000)
    return None


def filter_items_to_window(items: list[SquareItem | dict[str, Any]], *, hours: int) -> list[SquareItem | dict[str, Any]]:
    since_ms = int(window_start(hours).timestamp() * 1000)
    return [
        item
        for item in items
        if (_row_effective_timestamp_ms(item) or 0) >= since_ms
    ]


def extract_token_mentions(
    item: dict[str, Any],
    *,
    tradable_symbols: set[str] | None = None,
) -> list[str]:
    raw_candidates: list[str] = []
    for key in ("symbols", "token_mentions"):
        value = item.get(key)
        if isinstance(value, list):
            for candidate in value:
                if isinstance(candidate, str) and candidate.strip():
                    raw_candidates.append(candidate.strip())
    text = " ".join(
        str(item.get(field) or "")
        for field in ("title", "content", "excerpt")
    )
    for match in TOKEN_RE.findall(text):
        raw_candidates.append(match.upper())
    return sorted(filter_token_candidates(raw_candidates, tradable_symbols=tradable_symbols))


def _sort_key(item: dict[str, Any]) -> tuple[int, str]:
    ts = item.get("published_at")
    try:
        resolved_ts = int(float(ts)) if ts not in (None, "") else 0
    except Exception:
        resolved_ts = 0
    return (resolved_ts, str(item.get("external_id") or ""))


def dedupe_square_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for item in items:
        key = str(item.get("external_id") or item.get("url") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def prepare_square_item(
    item: dict[str, Any],
    *,
    tradable_symbols: set[str] | None = None,
) -> dict[str, Any]:
    prepared = dict(item)
    prepared["platform"] = str(prepared.get("platform") or "").lower()
    prepared["author_key"] = build_author_key(
        platform=prepared["platform"],
        author_id=prepared.get("author_id"),
        author_handle=prepared.get("author_handle"),
        author_name=prepared.get("author_name"),
    )
    prepared["token_mentions"] = extract_token_mentions(prepared, tradable_symbols=tradable_symbols)
    prepared["is_kol"] = int(bool(prepared.get("is_kol")))
    return prepared


async def _load_kol_profiles(platforms: list[str] | None = None) -> list[SquareKOLProfile]:
    if not db_available():
        return []
    async with async_session() as session:
        stmt = select(SquareKOLProfile).where(SquareKOLProfile.is_active == 1)
        if platforms:
            stmt = stmt.where(SquareKOLProfile.platform.in_(platforms))
        result = await session.execute(stmt.order_by(desc(SquareKOLProfile.score), SquareKOLProfile.name))
        return list(result.scalars().all())


def _build_kol_lookup(profiles: list[SquareKOLProfile]) -> dict[str, dict[str, dict[str, SquareKOLProfile]]]:
    lookup: dict[str, dict[str, dict[str, SquareKOLProfile]]] = {
        platform: {"handle": {}, "author_id": {}, "name": {}}
        for platform in SQUARE_PLATFORMS
    }
    for profile in profiles:
        platform = str(profile.platform or "").lower()
        if platform not in lookup:
            continue
        if normalize_identity(profile.handle):
            lookup[platform]["handle"][normalize_identity(profile.handle) or ""] = profile
        if normalize_identity(profile.author_id):
            lookup[platform]["author_id"][normalize_identity(profile.author_id) or ""] = profile
        names = [profile.name]
        if isinstance(profile.aliases_json, list):
            names.extend(alias for alias in profile.aliases_json if isinstance(alias, str))
        for name in names:
            normalized = normalize_identity(name)
            if normalized:
                lookup[platform]["name"][normalized] = profile
    return lookup


def apply_kol_matches(items: list[dict[str, Any]], profiles: list[SquareKOLProfile]) -> list[dict[str, Any]]:
    if not profiles:
        return items
    lookup = _build_kol_lookup(profiles)
    output: list[dict[str, Any]] = []
    for item in items:
        enriched = dict(item)
        platform = str(item.get("platform") or "").lower()
        matched: SquareKOLProfile | None = None
        platform_lookup = lookup.get(platform, {})
        author_id = normalize_identity(item.get("author_id"))
        author_handle = normalize_identity(item.get("author_handle"))
        author_name = normalize_identity(item.get("author_name"))
        if author_id:
            matched = platform_lookup.get("author_id", {}).get(author_id)
        if matched is None and author_handle:
            matched = platform_lookup.get("handle", {}).get(author_handle)
        if matched is None and author_name:
            matched = platform_lookup.get("name", {}).get(author_name)
        if matched is not None:
            enriched["is_kol"] = 1
            enriched["matched_kol_name"] = matched.name
            enriched["matched_kol_handle"] = matched.handle
            enriched["matched_kol_tier"] = matched.tier
        output.append(enriched)
    return output


async def prepare_square_items(
    items: list[dict[str, Any]],
    *,
    platforms: list[str] | tuple[str, ...] | None = None,
    profiles: list[SquareKOLProfile] | None = None,
) -> list[dict[str, Any]]:
    tradable_symbols = set(await load_tradable_symbols())
    prepared = [
        prepare_square_item(item, tradable_symbols=tradable_symbols or None)
        for item in dedupe_square_items(items)
    ]
    prepared.sort(key=_sort_key, reverse=True)
    resolved_profiles = profiles if profiles is not None else await _load_kol_profiles(normalize_platforms(platforms))
    return apply_kol_matches(prepared, resolved_profiles)


async def fetch_square_platform_page(
    platform: str,
    *,
    limit: int = 20,
    language: str | None = None,
    cursor: str | None = None,
    profiles: list[SquareKOLProfile] | None = None,
) -> dict[str, Any]:
    normalized_platform = str(platform or "").strip().lower()
    fetcher = SQUARE_SOURCE_FETCHERS.get(normalized_platform)
    if fetcher is None:
        raise ValueError(f"Unsupported square platform: {platform}")
    payload = await fetcher(
        language=language or settings.square_default_language,
        limit=limit,
        cursor=cursor,
    )
    items = await prepare_square_items(
        [item for item in payload.get("items", []) if isinstance(item, dict)],
        platforms=[normalized_platform],
        profiles=profiles,
    )
    normalized_payload = dict(payload)
    normalized_payload["platform"] = normalized_platform
    normalized_payload["items"] = items
    normalized_payload["count"] = len(items)
    return normalized_payload


async def fetch_square_feed(
    *,
    platforms: list[str] | tuple[str, ...] | None = None,
    limit: int = 20,
    language: str | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    selected = normalize_platforms(platforms)
    resolved_language = language or settings.square_default_language
    tasks: list[asyncio.Future] = []
    order: list[str] = []
    profiles = await _load_kol_profiles(selected)
    for platform in selected:
        order.append(platform)
        tasks.append(
            fetch_square_platform_page(
                platform,
                limit=limit,
                language=resolved_language,
                cursor=cursor,
                profiles=profiles,
            )
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)
    items: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    source_modes: dict[str, str] = {}
    warnings: list[str] = []
    next_cursors: dict[str, str | None] = {}

    for platform, result in zip(order, results):
        if isinstance(result, BaseException):
            errors.append({"platform": platform, "error": str(result)})
            continue
        source_modes[platform] = str(result.get("source_mode") or "api")
        if result.get("warning"):
            warnings.append(str(result["warning"]))
        next_cursors[platform] = result.get("next_cursor")
        items.extend(item for item in result.get("items", []) if isinstance(item, dict))

    prepared = await prepare_square_items(items, platforms=selected, profiles=profiles)
    prepared = prepared[: max(1, min(limit, 100))]
    return {
        "items": prepared,
        "count": len(prepared),
        "platforms": selected,
        "source_modes": source_modes,
        "errors": errors,
        "warnings": warnings,
        "next_cursors": next_cursors,
    }


def filter_square_items(
    items: list[dict[str, Any]],
    *,
    platform: str | None = None,
    item_type: str | None = None,
    language: str | None = None,
    q: str | None = None,
    kol_only: bool = False,
) -> list[dict[str, Any]]:
    keyword = (q or "").strip().lower()
    normalized_platform = (platform or "").strip().lower() or None
    normalized_type = (item_type or "").strip().lower() or None
    normalized_language = normalize_language(language)
    filtered = items
    if normalized_platform in SQUARE_PLATFORMS:
        filtered = [item for item in filtered if str(item.get("platform") or "").lower() == normalized_platform]
    if normalized_type in SQUARE_ITEM_TYPES:
        filtered = [item for item in filtered if str(item.get("item_type") or "").lower() == normalized_type]
    if normalized_language:
        filtered = [
            item
            for item in filtered
            if (normalize_language(item.get("language")) or "").startswith(normalized_language)
        ]
    if kol_only:
        filtered = [item for item in filtered if int(item.get("is_kol") or 0) == 1]
    if keyword:
        filtered = [
            item
            for item in filtered
            if keyword in " ".join(
                str(item.get(field) or "")
                for field in ("title", "content", "author_name", "author_handle", "matched_kol_name")
            ).lower()
        ]
    return filtered


def serialize_square_row(item: SquareItem) -> dict[str, Any]:
    stored_at = getattr(item, "created_at", None)
    raw_symbols = item.symbols_json or []
    cleaned_token_mentions = extract_token_mentions(
        {
            "symbols": raw_symbols,
            "title": item.title,
            "content": item.content,
            "excerpt": (item.content or item.title or "")[:280] or None,
        }
    )
    return {
        "id": item.id,
        "external_id": item.external_id,
        "platform": item.platform,
        "channel": item.channel,
        "item_type": item.item_type,
        "title": item.title,
        "content": item.content,
        "excerpt": (item.content or item.title or "")[:280] or None,
        "author_id": item.author_id,
        "author_key": item.author_key,
        "author_name": item.author_name,
        "author_handle": item.author_handle,
        "is_kol": bool(item.is_kol),
        "matched_kol_name": item.matched_kol_name,
        "matched_kol_handle": item.matched_kol_handle,
        "matched_kol_tier": item.matched_kol_tier,
        "language": item.language,
        "published_at": item.published_at,
        "url": item.url,
        "engagement": item.engagement_json or {},
        "symbols": raw_symbols,
        "token_mentions": cleaned_token_mentions,
        "tags": item.tags_json or [],
        "metadata": item.metadata_json or {},
        "stored_at": str(stored_at) if stored_at else None,
    }


def serialize_live_square_item(item: dict[str, Any], index: int) -> dict[str, Any]:
    title = item.get("title")
    content = item.get("content")
    return {
        "id": item.get("external_id") or f"square_live_{index}",
        "external_id": item.get("external_id"),
        "platform": item.get("platform", ""),
        "channel": item.get("channel", "square"),
        "item_type": item.get("item_type", "post"),
        "title": title,
        "content": content,
        "excerpt": item.get("excerpt") or (content or title or "")[:280] or None,
        "author_id": item.get("author_id"),
        "author_key": item.get("author_key"),
        "author_name": item.get("author_name"),
        "author_handle": item.get("author_handle"),
        "is_kol": bool(item.get("is_kol")),
        "matched_kol_name": item.get("matched_kol_name"),
        "matched_kol_handle": item.get("matched_kol_handle"),
        "matched_kol_tier": item.get("matched_kol_tier"),
        "language": item.get("language"),
        "published_at": item.get("published_at"),
        "url": item.get("url"),
        "engagement": item.get("engagement") if isinstance(item.get("engagement"), dict) else {},
        "symbols": item.get("symbols") if isinstance(item.get("symbols"), list) else [],
        "token_mentions": item.get("token_mentions") if isinstance(item.get("token_mentions"), list) else [],
        "tags": item.get("tags") if isinstance(item.get("tags"), list) else [],
        "metadata": item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
        "stored_at": item.get("published_at"),
    }


def build_hot_token_board(
    items: list[dict[str, Any]],
    *,
    limit: int = 20,
    tradable_symbols: set[str] | None = None,
    min_unique_authors: int = 1,
    min_unique_kol_mentions: int = 0,
) -> list[dict[str, Any]]:
    author_mentions_seen: set[tuple[str, str]] = set()
    kol_mentions_seen: set[tuple[str, str]] = set()
    token_stats: dict[str, dict[str, Any]] = {}

    for item in items:
        author_key = str(item.get("author_key") or item.get("external_id") or "")
        tokens = sorted(
            {
                token
                for token in extract_token_mentions(item, tradable_symbols=tradable_symbols)
                if token
            }
        )
        if not author_key or not tokens:
            continue
        platform = str(item.get("platform") or "")
        published_at = item.get("published_at")
        author_label = item.get("matched_kol_name") or item.get("author_name") or item.get("author_handle") or author_key
        for token in tokens:
            stat = token_stats.setdefault(
                token,
                {
                    "token": token,
                    "unique_author_mentions": 0,
                    "unique_kol_mentions": 0,
                    "item_count": 0,
                    "platforms": set(),
                    "sample_authors": [],
                    "latest_published_at": published_at,
                },
            )
            stat["item_count"] += 1
            stat["platforms"].add(platform)
            if published_at not in (None, ""):
                try:
                    if int(float(published_at)) > int(float(stat["latest_published_at"] or 0)):
                        stat["latest_published_at"] = published_at
                except Exception:
                    pass
            author_pair = (token, author_key)
            if author_pair not in author_mentions_seen:
                author_mentions_seen.add(author_pair)
                stat["unique_author_mentions"] += 1
                if len(stat["sample_authors"]) < 5:
                    stat["sample_authors"].append(author_label)
            if int(item.get("is_kol") or 0) == 1 and author_pair not in kol_mentions_seen:
                kol_mentions_seen.add(author_pair)
                stat["unique_kol_mentions"] += 1

    filtered_ranked = [
        item
        for item in token_stats.values()
        if (
            int(item["unique_author_mentions"]) >= max(1, min_unique_authors)
            or int(item["unique_kol_mentions"]) >= max(0, min_unique_kol_mentions)
        )
    ]

    ranked = sorted(
        filtered_ranked,
        key=lambda item: (
            int(item["unique_author_mentions"]),
            int(item["unique_kol_mentions"]),
            int(item["item_count"]),
            str(item["token"]),
        ),
        reverse=True,
    )
    output: list[dict[str, Any]] = []
    for index, item in enumerate(ranked[: max(1, min(limit, 100))], start=1):
        output.append(
            {
                "rank": index,
                "token": item["token"],
                "unique_author_mentions": item["unique_author_mentions"],
                "unique_kol_mentions": item["unique_kol_mentions"],
                "item_count": item["item_count"],
                "platforms": sorted(item["platforms"]),
                "sample_authors": item["sample_authors"],
                "latest_published_at": item["latest_published_at"],
            }
        )
    return output


def snapshot_key_for(
    *,
    snapshot_date: str,
    platforms: list[str],
    window_hours: int,
    kol_only: bool,
) -> str:
    platform_scope = ",".join(platforms)
    suffix = "kol" if kol_only else "all"
    return f"{snapshot_date}:{platform_scope}:{window_hours}h:{suffix}"


async def load_hot_coin_board(
    *,
    platforms: list[str] | tuple[str, ...] | None = None,
    hours: int = 24,
    kol_only: bool = False,
    limit: int = 20,
    language: str | None = None,
    min_unique_authors: int | None = None,
    min_unique_kol_mentions: int | None = None,
) -> dict[str, Any]:
    selected_platforms = normalize_platforms(platforms)
    resolved_hours = max(1, min(hours, 168))
    tradable_symbols = set(await load_tradable_symbols()) or None
    min_unique_authors = max(
        1,
        int(
            settings.square_hot_token_min_unique_authors
            if min_unique_authors is None
            else min_unique_authors
        ),
    )
    min_unique_kol_mentions = max(
        0,
        int(
            settings.square_hot_token_min_unique_kol_mentions
            if min_unique_kol_mentions is None
            else min_unique_kol_mentions
        ),
    )
    if not db_available():
        payload = await fetch_square_feed(
            platforms=selected_platforms,
            limit=100,
            language=language or settings.square_default_language,
        )
        filtered = filter_square_items(
            payload.get("items", []),
            language=language,
            kol_only=kol_only,
        )
        board = build_hot_token_board(
            filtered,
            limit=limit,
            tradable_symbols=tradable_symbols,
            min_unique_authors=min_unique_authors,
            min_unique_kol_mentions=min_unique_kol_mentions,
        )
        return {
            "items": board,
            "count": len(board),
            "db_available": False,
            "source_mode": "live",
            "window_hours": resolved_hours,
            "platforms": selected_platforms,
            "warnings": payload.get("warnings", []),
            "errors": payload.get("errors", []),
        }

    since_dt = window_start(resolved_hours)
    since_ms = int(since_dt.timestamp() * 1000)
    published_at_expr = _square_published_at_expr()
    async with async_session() as session:
        stmt = select(SquareItem).where(
            SquareItem.platform.in_(selected_platforms),
            or_(
                published_at_expr >= since_ms,
                and_(SquareItem.published_at.is_(None), SquareItem.created_at >= since_dt),
            ),
        )
        if kol_only:
            stmt = stmt.where(SquareItem.is_kol == 1)
        rows = (
            await session.execute(
                stmt.order_by(desc(published_at_expr), desc(SquareItem.created_at)).limit(4000)
            )
        ).scalars().all()

    serialized = [serialize_square_row(row) for row in filter_items_to_window(list(rows), hours=resolved_hours)]
    board = build_hot_token_board(
        serialized,
        limit=limit,
        tradable_symbols=tradable_symbols,
        min_unique_authors=min_unique_authors,
        min_unique_kol_mentions=min_unique_kol_mentions,
    )
    return {
        "items": board,
        "count": len(board),
        "db_available": True,
        "source_mode": "database",
        "window_hours": resolved_hours,
        "window_start": since_dt.astimezone(timezone.utc).isoformat(),
        "platforms": selected_platforms,
        "kol_only": kol_only,
        "min_unique_authors": min_unique_authors,
        "min_unique_kol_mentions": min_unique_kol_mentions,
    }


async def generate_hot_coin_snapshot(
    *,
    platforms: list[str] | tuple[str, ...] | None = None,
    hours: int = 24,
    kol_only: bool = False,
    limit: int = 20,
    snapshot_date: str | None = None,
) -> dict[str, Any]:
    if not db_available():
        raise RuntimeError("Database not available")
    selected_platforms = normalize_platforms(platforms)
    resolved_hours = max(1, min(hours, 168))
    resolved_snapshot_date = snapshot_date or datetime.now(timezone.utc).date().isoformat()
    board_payload = await load_hot_coin_board(
        platforms=selected_platforms,
        hours=resolved_hours,
        kol_only=kol_only,
        limit=limit,
    )
    snapshot_key = snapshot_key_for(
        snapshot_date=resolved_snapshot_date,
        platforms=selected_platforms,
        window_hours=resolved_hours,
        kol_only=kol_only,
    )
    created = 0
    async with async_session() as session:
        existing_rows = (
            await session.execute(
                select(SquareHotTokenSnapshot).where(SquareHotTokenSnapshot.snapshot_key == snapshot_key)
            )
        ).scalars().all()
        for row in existing_rows:
            await session.delete(row)
        await session.flush()

        for item in board_payload.get("items", []):
            session.add(
                SquareHotTokenSnapshot(
                    snapshot_key=snapshot_key,
                    snapshot_date=resolved_snapshot_date,
                    window_hours=resolved_hours,
                    platform_scope=",".join(selected_platforms),
                    kol_only=1 if kol_only else 0,
                    rank=int(item.get("rank") or 0),
                    token=str(item.get("token") or "")[:20],
                    unique_author_mentions=int(item.get("unique_author_mentions") or 0),
                    unique_kol_mentions=int(item.get("unique_kol_mentions") or 0),
                    item_count=int(item.get("item_count") or 0),
                    platforms_json=item.get("platforms") if isinstance(item.get("platforms"), list) else None,
                    sample_authors_json=item.get("sample_authors") if isinstance(item.get("sample_authors"), list) else None,
                    latest_published_at=str(item.get("latest_published_at")) if item.get("latest_published_at") not in (None, "") else None,
                    metadata_json={
                        "window_hours": resolved_hours,
                        "platforms": selected_platforms,
                        "kol_only": kol_only,
                    },
                )
            )
            created += 1
        await session.commit()

    return {
        "snapshot_key": snapshot_key,
        "snapshot_date": resolved_snapshot_date,
        "window_hours": resolved_hours,
        "platforms": selected_platforms,
        "kol_only": kol_only,
        "items": board_payload.get("items", []),
        "count": created,
        "replaced": len(existing_rows),
    }


async def upsert_kol_profiles(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not db_available():
        raise RuntimeError("Database not available")
    created = 0
    updated = 0
    async with async_session() as session:
        for row in rows:
            platform = str(row.get("platform") or "").strip().lower()
            handle = row.get("handle")
            name = str(row.get("name") or "").strip()
            author_id = row.get("author_id")
            if platform not in SQUARE_PLATFORMS or not name:
                continue
            stmt = select(SquareKOLProfile).where(
                SquareKOLProfile.platform == platform,
                func.coalesce(SquareKOLProfile.handle, "") == str(handle or ""),
                func.coalesce(SquareKOLProfile.author_id, "") == str(author_id or ""),
                SquareKOLProfile.name == name,
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()
            aliases = row.get("aliases") if isinstance(row.get("aliases"), list) else None
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else None
            is_active = 1 if row.get("is_active", True) else 0
            if existing is None:
                session.add(
                    SquareKOLProfile(
                        platform=platform,
                        name=name,
                        handle=handle,
                        author_id=author_id,
                        aliases_json=aliases,
                        tier=row.get("tier"),
                        score=row.get("score"),
                        is_active=is_active,
                        metadata_json=metadata,
                    )
                )
                created += 1
            else:
                existing.aliases_json = aliases
                existing.tier = row.get("tier")
                existing.score = row.get("score")
                existing.is_active = is_active
                existing.metadata_json = metadata
                existing.handle = handle
                existing.author_id = author_id
                updated += 1
        await session.commit()
    return {"created": created, "updated": updated, "count": created + updated}


def window_start(hours: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=max(1, hours))


async def list_kol_profiles(platform: str | None = None) -> list[SquareKOLProfile]:
    selected = normalize_platforms([platform] if platform else None)
    return await _load_kol_profiles(selected)


async def list_hot_coin_snapshots(
    *,
    snapshot_date: str | None = None,
    platforms: list[str] | tuple[str, ...] | None = None,
    kol_only: bool | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    selected_platforms = normalize_platforms(platforms)
    if not db_available():
        raise RuntimeError("Database not available")

    async with async_session() as session:
        stmt = select(SquareHotTokenSnapshot)
        if snapshot_date:
            stmt = stmt.where(SquareHotTokenSnapshot.snapshot_date == snapshot_date)
        else:
            latest_stmt = select(func.max(SquareHotTokenSnapshot.snapshot_date))
            latest_date = (await session.execute(latest_stmt)).scalar_one_or_none()
            if latest_date:
                stmt = stmt.where(SquareHotTokenSnapshot.snapshot_date == latest_date)
        stmt = stmt.where(SquareHotTokenSnapshot.platform_scope == ",".join(selected_platforms))
        if kol_only is not None:
            stmt = stmt.where(SquareHotTokenSnapshot.kol_only == (1 if kol_only else 0))
        stmt = stmt.order_by(
            desc(SquareHotTokenSnapshot.snapshot_date),
            desc(SquareHotTokenSnapshot.kol_only),
            SquareHotTokenSnapshot.rank,
        ).limit(max(1, min(limit, 200)))
        rows = (await session.execute(stmt)).scalars().all()

    return {
        "items": [
            {
                "snapshot_key": row.snapshot_key,
                "snapshot_date": row.snapshot_date,
                "window_hours": row.window_hours,
                "platform_scope": row.platform_scope,
                "kol_only": bool(row.kol_only),
                "rank": row.rank,
                "token": row.token,
                "unique_author_mentions": row.unique_author_mentions,
                "unique_kol_mentions": row.unique_kol_mentions,
                "item_count": row.item_count,
                "platforms": row.platforms_json or [],
                "sample_authors": row.sample_authors_json or [],
                "latest_published_at": row.latest_published_at,
                "stored_at": str(row.created_at) if row.created_at else None,
            }
            for row in rows
        ],
        "count": len(rows),
    }


def serialize_collection_state(item: SquareCollectionState) -> dict[str, Any]:
    stored_at = getattr(item, "created_at", None)
    return {
        "id": item.id,
        "platform": item.platform,
        "language": item.language,
        "current_cursor": item.current_cursor,
        "last_status": item.last_status,
        "last_run_started_at": item.last_run_started_at.isoformat() if item.last_run_started_at else None,
        "last_run_finished_at": item.last_run_finished_at.isoformat() if item.last_run_finished_at else None,
        "last_created_count": item.last_created_count,
        "last_skipped_count": item.last_skipped_count,
        "last_page_count": item.last_page_count,
        "metadata": item.metadata_json or {},
        "stored_at": stored_at.isoformat() if stored_at else None,
    }


def _build_square_row(item: dict[str, Any]) -> SquareItem:
    ext_id = item.get("external_id")
    return SquareItem(
        platform=str(item.get("platform") or "")[:20],
        channel=str(item.get("channel") or "square")[:20],
        item_type=str(item.get("item_type") or "post")[:20],
        title=(str(item.get("title"))[:500] if item.get("title") is not None else None),
        content=item.get("content"),
        author_id=(str(item.get("author_id"))[:120] if item.get("author_id") is not None else None),
        author_key=(str(item.get("author_key"))[:180] if item.get("author_key") is not None else None),
        author_name=(str(item.get("author_name"))[:120] if item.get("author_name") is not None else None),
        author_handle=(str(item.get("author_handle"))[:120] if item.get("author_handle") is not None else None),
        is_kol=int(item.get("is_kol") or 0),
        matched_kol_name=(str(item.get("matched_kol_name"))[:120] if item.get("matched_kol_name") is not None else None),
        matched_kol_handle=(str(item.get("matched_kol_handle"))[:120] if item.get("matched_kol_handle") is not None else None),
        matched_kol_tier=(str(item.get("matched_kol_tier"))[:30] if item.get("matched_kol_tier") is not None else None),
        language=(str(item.get("language"))[:20] if item.get("language") is not None else None),
        published_at=str(item.get("published_at")) if item.get("published_at") not in (None, "") else None,
        url=item.get("url"),
        external_id=(str(ext_id)[:150] if ext_id is not None else None),
        engagement_json=item.get("engagement") if isinstance(item.get("engagement"), dict) else None,
        symbols_json=item.get("token_mentions") if isinstance(item.get("token_mentions"), list) else None,
        tags_json=item.get("tags") if isinstance(item.get("tags"), list) else None,
        metadata_json=item.get("metadata") if isinstance(item.get("metadata"), dict) else None,
    )


async def _persist_square_items(session: Any, items: list[dict[str, Any]]) -> dict[str, int]:
    ext_ids = [
        str(item.get("external_id"))
        for item in items
        if item.get("external_id") not in (None, "")
    ]
    existing_ids: set[str] = set()
    if ext_ids:
        existing_ids = set(
            str(value)
            for value in (
                await session.execute(select(SquareItem.external_id).where(SquareItem.external_id.in_(ext_ids)))
            ).scalars().all()
            if value not in (None, "")
        )

    created = 0
    skipped = 0
    seen_new_ids: set[str] = set()
    for item in items:
        ext_id = str(item.get("external_id") or "").strip()
        if ext_id and (ext_id in existing_ids or ext_id in seen_new_ids):
            skipped += 1
            continue
        session.add(_build_square_row(item))
        created += 1
        if ext_id:
            seen_new_ids.add(ext_id)
    return {"created": created, "skipped": skipped}


async def _get_or_create_collection_state(
    session: Any,
    *,
    platform: str,
    language: str,
) -> SquareCollectionState:
    stmt = select(SquareCollectionState).where(
        SquareCollectionState.platform == platform,
        SquareCollectionState.language == language,
    )
    state = (await session.execute(stmt)).scalar_one_or_none()
    if state is not None:
        return state
    state = SquareCollectionState(
        platform=platform,
        language=language,
        current_cursor=None,
        last_status="idle",
        metadata_json={},
    )
    session.add(state)
    await session.flush()
    return state


async def list_square_collection_states(
    *,
    platforms: list[str] | tuple[str, ...] | None = None,
    language: str | None = None,
) -> list[dict[str, Any]]:
    if not db_available():
        return []
    selected_platforms = normalize_platforms(platforms)
    async with async_session() as session:
        stmt = select(SquareCollectionState).where(SquareCollectionState.platform.in_(selected_platforms))
        normalized_language = normalize_language(language)
        if normalized_language:
            stmt = stmt.where(SquareCollectionState.language == normalized_language)
        stmt = stmt.order_by(SquareCollectionState.platform, SquareCollectionState.language)
        rows = (await session.execute(stmt)).scalars().all()
    return [serialize_collection_state(row) for row in rows]


async def collect_square_platform_items(
    platform: str,
    *,
    page_size: int | None = None,
    backfill_pages: int | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    if not db_available():
        return {
            "platform": platform,
            "language": language or settings.square_default_language,
            "created": 0,
            "skipped": 0,
            "fetched": 0,
            "pages": 0,
            "next_cursor": None,
        }

    normalized_platform = str(platform or "").strip().lower()
    resolved_language = normalize_language(language) or settings.square_default_language
    resolved_page_size = max(1, min(page_size or settings.square_collect_page_size, 50))
    resolved_backfill_pages = max(0, min(backfill_pages or settings.square_collect_backfill_pages, 10))
    total_created = 0
    total_skipped = 0
    total_fetched = 0
    pages = 0
    warnings: list[str] = []
    frontfill_cursor: str | None = None
    next_cursor: str | None = None
    started_at = utcnow_naive()
    profiles = await _load_kol_profiles([normalized_platform])

    async with async_session() as session:
        state = await _get_or_create_collection_state(
            session,
            platform=normalized_platform,
            language=resolved_language,
        )
        state.last_status = "running"
        state.last_run_started_at = started_at
        state.last_run_finished_at = None
        await session.flush()

        try:
            fetched_input_cursors: set[str] = set()
            current_cursor: str | None = None
            for _ in range(DEFAULT_COLLECT_FRONTFILL_PAGES):
                payload = await fetch_square_platform_page(
                    normalized_platform,
                    limit=resolved_page_size,
                    language=resolved_language,
                    cursor=current_cursor,
                    profiles=profiles,
                )
                counts = await _persist_square_items(session, payload.get("items", []))
                total_created += counts["created"]
                total_skipped += counts["skipped"]
                total_fetched += int(payload.get("count") or 0)
                pages += 1
                if payload.get("warning"):
                    warnings.append(str(payload.get("warning")))
                if current_cursor is not None:
                    fetched_input_cursors.add(current_cursor)
                next_cursor = payload.get("next_cursor")
                if not next_cursor:
                    frontfill_cursor = None
                    break
                current_cursor = str(next_cursor)
                frontfill_cursor = current_cursor

            continue_cursor = state.current_cursor or frontfill_cursor
            if continue_cursor in fetched_input_cursors:
                continue_cursor = frontfill_cursor

            visited_cursors: set[str] = set()
            while continue_cursor and len(visited_cursors) < resolved_backfill_pages:
                visited_cursors.add(continue_cursor)
                payload = await fetch_square_platform_page(
                    normalized_platform,
                    limit=resolved_page_size,
                    language=resolved_language,
                    cursor=continue_cursor,
                    profiles=profiles,
                )
                counts = await _persist_square_items(session, payload.get("items", []))
                total_created += counts["created"]
                total_skipped += counts["skipped"]
                total_fetched += int(payload.get("count") or 0)
                pages += 1
                if payload.get("warning"):
                    warnings.append(str(payload.get("warning")))
                next_cursor = payload.get("next_cursor")
                if not next_cursor or next_cursor in visited_cursors:
                    continue_cursor = None
                    break
                continue_cursor = str(next_cursor)

            state.current_cursor = continue_cursor
            state.last_status = "ok"
            state.last_run_finished_at = utcnow_naive()
            state.last_created_count = total_created
            state.last_skipped_count = total_skipped
            state.last_page_count = pages
            state.metadata_json = {
                "last_fetched_count": total_fetched,
                "page_size": resolved_page_size,
                "frontfill_pages": DEFAULT_COLLECT_FRONTFILL_PAGES,
                "backfill_pages": resolved_backfill_pages,
                "warnings": warnings,
            }
            await session.commit()
        except Exception as exc:
            state.last_status = "error"
            state.last_run_finished_at = utcnow_naive()
            state.last_created_count = total_created
            state.last_skipped_count = total_skipped
            state.last_page_count = pages
            state.metadata_json = {
                "last_fetched_count": total_fetched,
                "page_size": resolved_page_size,
                "frontfill_pages": DEFAULT_COLLECT_FRONTFILL_PAGES,
                "backfill_pages": resolved_backfill_pages,
                "warnings": warnings,
                "last_error": str(exc),
            }
            await session.commit()
            raise

    return {
        "platform": normalized_platform,
        "language": resolved_language,
        "created": total_created,
        "skipped": total_skipped,
        "fetched": total_fetched,
        "pages": pages,
        "next_cursor": continue_cursor,
        "warnings": warnings,
    }


async def collect_square_items(
    *,
    platforms: list[str] | tuple[str, ...] | None = None,
    page_size: int | None = None,
    backfill_pages: int | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    selected_platforms = normalize_platforms(platforms)
    if not db_available():
        return {"created": 0, "skipped": 0, "fetched": 0, "pages": 0, "results": []}

    results: list[dict[str, Any]] = []
    total_created = 0
    total_skipped = 0
    total_fetched = 0
    total_pages = 0
    for platform in selected_platforms:
        result = await collect_square_platform_items(
            platform,
            page_size=page_size,
            backfill_pages=backfill_pages,
            language=language,
        )
        results.append(result)
        total_created += int(result.get("created") or 0)
        total_skipped += int(result.get("skipped") or 0)
        total_fetched += int(result.get("fetched") or 0)
        total_pages += int(result.get("pages") or 0)
    return {
        "platforms": selected_platforms,
        "created": total_created,
        "skipped": total_skipped,
        "fetched": total_fetched,
        "pages": total_pages,
        "results": results,
    }


async def query_square_history(
    *,
    platform: str | None,
    item_type: str | None,
    language: str | None,
    q: str | None,
    kol_only: bool,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    normalized_platform = (platform or "").strip().lower() or None
    normalized_type = (item_type or "").strip().lower() or None
    normalized_language = normalize_language(language)
    keyword = (q or "").strip()

    if not db_available():
        payload = await fetch_square_feed(
            platforms=normalize_platforms([normalized_platform] if normalized_platform else None),
            limit=min(max(page * page_size, page_size), 100),
            language=normalized_language or settings.square_default_language,
        )
        filtered = filter_square_items(
            payload.get("items", []),
            platform=normalized_platform,
            item_type=normalized_type,
            language=normalized_language,
            q=keyword,
            kol_only=kol_only,
        )
        start = (page - 1) * page_size
        end = start + page_size
        page_items = filtered[start:end]
        return {
            "items": [serialize_live_square_item(item, index + start) for index, item in enumerate(page_items)],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": len(filtered),
                "total_pages": math.ceil(len(filtered) / page_size) if filtered else 0,
                "has_prev": page > 1,
                "has_next": end < len(filtered),
            },
            "db_available": False,
            "source_mode": "live",
            "source_modes": payload.get("source_modes", {}),
            "errors": payload.get("errors", []),
            "warnings": payload.get("warnings", []),
        }

    async with async_session() as session:
        conditions = []
        published_at_expr = _square_published_at_expr()
        if normalized_platform in SQUARE_PLATFORMS:
            conditions.append(SquareItem.platform == normalized_platform)
        if normalized_type in SQUARE_ITEM_TYPES:
            conditions.append(SquareItem.item_type == normalized_type)
        if normalized_language:
            conditions.append(func.lower(SquareItem.language).like(f"{normalized_language}%"))
        if kol_only:
            conditions.append(SquareItem.is_kol == 1)
        if keyword:
            pattern = f"%{keyword}%"
            conditions.append(
                or_(
                    SquareItem.title.ilike(pattern),
                    SquareItem.content.ilike(pattern),
                    SquareItem.author_name.ilike(pattern),
                    SquareItem.author_handle.ilike(pattern),
                    SquareItem.matched_kol_name.ilike(pattern),
                )
            )

        total_stmt = select(func.count()).select_from(SquareItem)
        if conditions:
            total_stmt = total_stmt.where(*conditions)
        total = int((await session.execute(total_stmt)).scalar() or 0)
        total_pages = math.ceil(total / page_size) if total else 0
        current_page = min(page, total_pages) if total_pages else 1

        stmt = select(SquareItem)
        if conditions:
            stmt = stmt.where(*conditions)
        stmt = (
            stmt.order_by(desc(published_at_expr), desc(SquareItem.created_at))
            .offset((current_page - 1) * page_size)
            .limit(page_size)
        )
        rows = (await session.execute(stmt)).scalars().all()

    return {
        "items": [serialize_square_row(row) for row in rows],
        "pagination": {
            "page": current_page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "has_prev": current_page > 1,
            "has_next": current_page < total_pages,
        },
        "db_available": True,
        "source_mode": "database",
    }
