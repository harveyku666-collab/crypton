"""Binance Square API adapter backed by Binance's public web feed API."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urljoin
from uuid import uuid4

from app.common.cache import cached
from app.common.http_client import fetch_json, fetch_json_post
from app.config import settings

BASE = "https://www.binance.com"
DEFAULT_FEED_URL = f"{BASE}/bapi/composite/v9/friendly/pgc/feed/feed-recommend/list"
DEFAULT_DETAIL_URL = f"{BASE}/bapi/composite/v2/friendly/pgc/special/content/detail"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/139.0.0.0 Safari/537.36"
)
MAX_PAGE_SIZE = 50
MAX_DETAIL_ENRICH = 6


def _normalize_language(language: str | None) -> str:
    normalized = (language or "en").strip().lower().replace("_", "-")
    if normalized.startswith("zh"):
        return "zh-CN"
    return "en"


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except Exception:
        return None


def _to_millis(value: Any) -> int | None:
    ts = _safe_int(value)
    if ts is None:
        return None
    if abs(ts) < 10**12:
        return ts * 1000
    return ts


def _first_string(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
    return None


def _normalize_page_index(cursor: str | None) -> int:
    page = _safe_int(cursor)
    if page is None or page < 1:
        return 1
    return page


def _build_referer(language: str) -> str:
    locale = "zh-CN" if language == "zh-CN" else "en"
    return f"{BASE}/{locale}/square"


def _build_headers(language: str, *, referer: str | None = None) -> dict[str, str]:
    request_id = str(uuid4()).lower()
    resolved_referer = referer or _build_referer(language)
    cookie_parts = [f"lang={language}", f"bnc-uid={request_id}"]
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": DEFAULT_USER_AGENT,
        "Origin": BASE,
        "Referer": resolved_referer,
        "Bnc-Uuid": request_id,
        "Clienttype": "web",
        "Versioncode": "web",
        "lang": language,
        "Cookie": "; ".join(cookie_parts),
    }


def _translated_text(item: dict[str, Any], key: str) -> str | None:
    translated = item.get("translatedData")
    if not isinstance(translated, dict):
        return None
    value = translated.get(key)
    if isinstance(value, str):
        text = value.strip()
        if text:
            return text
    return None


def _resolve_text(item: dict[str, Any], *, language: str, key: str) -> str | None:
    if language == "zh-CN":
        translated = _translated_text(item, key)
        if translated:
            return translated
    return _first_string(item, key)


def _resolve_item_type(item: dict[str, Any]) -> str:
    card_type = str(item.get("cardType") or "").upper()
    content_type = _safe_int(item.get("contentType"))
    if content_type == 2 or "LONG" in card_type:
        return "article"
    return "post"


def _extract_symbols(item: dict[str, Any], text: str | None) -> list[str]:
    symbols: set[str] = set()
    for key in ("tradingPairs", "tradingPairsV2", "userInputTradingPairs", "tradeWidgets"):
        value = item.get(key)
        if isinstance(value, list):
            for candidate in value:
                if not isinstance(candidate, dict):
                    continue
                for nested_key in ("code", "coin", "baseAsset", "asset"):
                    nested = candidate.get(nested_key)
                    if isinstance(nested, str) and nested.strip():
                        symbols.add(nested.strip().upper())
                symbol = candidate.get("symbol")
                bridge = candidate.get("bridge")
                if (
                    isinstance(symbol, str)
                    and symbol.strip()
                    and isinstance(bridge, str)
                    and bridge.strip()
                    and symbol.upper().endswith(bridge.upper())
                ):
                    trimmed = symbol[: -len(bridge)].strip().upper()
                    if trimmed:
                        symbols.add(trimmed)
    token_map = item.get("tokensBodyMap")
    if isinstance(token_map, dict):
        for candidate in token_map.values():
            if not isinstance(candidate, dict):
                continue
            for nested_key in ("code", "coin", "baseAsset", "asset"):
                nested = candidate.get(nested_key)
                if isinstance(nested, str) and nested.strip():
                    symbols.add(nested.strip().upper())
    coin_pair_list = item.get("coinPairList")
    if isinstance(coin_pair_list, list):
        for candidate in coin_pair_list:
            if not isinstance(candidate, str):
                continue
            cleaned = candidate.strip().lstrip("$#").strip().upper()
            if cleaned:
                symbols.add(cleaned)
    if text:
        import re

        for match in re.findall(r"[$#]([A-Za-z][A-Za-z0-9]{1,14})", text):
            symbols.add(match.upper())
    return sorted(symbols)


def _extract_tags(item: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for candidate in item.get("hashtagList", []) or []:
        if not isinstance(candidate, str):
            continue
        cleaned = candidate.strip().lstrip("#").strip()
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            tags.append(cleaned)
    return tags


def _merge_lists(*values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for collection in values:
        for candidate in collection:
            cleaned = str(candidate or "").strip()
            if not cleaned:
                continue
            marker = cleaned.lower()
            if marker in seen:
                continue
            seen.add(marker)
            output.append(cleaned)
    return output


def _normalize_item(item: dict[str, Any], *, language: str) -> dict[str, Any] | None:
    title = _resolve_text(item, language=language, key="title")
    subtitle = _resolve_text(item, language=language, key="subTitle")
    content = _resolve_text(item, language=language, key="content")
    raw_id = _first_string(item, "id")
    share_url = _first_string(item, "webLink", "shareLink")
    if share_url and share_url.startswith("/"):
        share_url = urljoin(BASE, share_url)
    if not share_url and raw_id:
        share_url = f"{BASE}/square/post/{raw_id}"

    if not title and not subtitle and not content:
        return None

    item_type = _resolve_item_type(item)
    author_id = _first_string(item, "squareAuthorId")
    author_name = _first_string(item, "authorName")
    author_handle = _first_string(item, "username")
    author_verification_type = _safe_int(item.get("authorVerificationType")) or 0
    author_role = _safe_int(item.get("authorRole")) or 0
    is_native_kol = author_verification_type > 0 or author_role != 0
    visible_content = content or subtitle
    full_text = " ".join(part for part in [title, subtitle, content] if part)
    if not raw_id:
        return None
    return {
        "external_id": f"binance_{raw_id}",
        "platform": "binance",
        "channel": "square",
        "item_type": item_type,
        "title": title,
        "content": visible_content,
        "excerpt": (visible_content or title or "")[:280] or None,
        "author_id": author_id,
        "author_name": author_name,
        "author_handle": author_handle,
        "is_kol": 1 if is_native_kol else 0,
        "matched_kol_name": author_name if is_native_kol else None,
        "matched_kol_handle": author_handle if is_native_kol else None,
        "matched_kol_tier": "platform_native" if is_native_kol else None,
        "language": language,
        "published_at": _to_millis(item.get("date")),
        "url": share_url,
        "engagement": {
            "likes": _safe_int(item.get("likeCount")),
            "comments": _safe_int(item.get("commentCount")),
            "views": _safe_int(item.get("viewCount")),
            "shares": _safe_int(item.get("shareCount")),
            "quotes": _safe_int(item.get("quoteCount")),
        },
        "symbols": _extract_symbols(item, full_text),
        "tags": _extract_tags(item),
        "metadata": {
            "raw_id": raw_id,
            "card_type": item.get("cardType"),
            "content_type": _safe_int(item.get("contentType")),
            "author_verification_type": author_verification_type,
            "author_role": author_role,
            "source_type": _safe_int(item.get("sourceType")),
            "quoted_content_web_link": item.get("quotedContentWebLink"),
            "is_featured": bool(item.get("isFeatured")),
            "is_live": bool((item.get("liveStatusVO") or {}).get("isLive")) if isinstance(item.get("liveStatusVO"), dict) else False,
            "source_mode": "api",
        },
    }


def _should_enrich_item(item: dict[str, Any]) -> bool:
    if str(item.get("item_type") or "").lower() == "article":
        return True
    return not bool(str(item.get("content") or "").strip())


def _pick_detail_value(detail: dict[str, Any], language: str, *keys: str) -> str | None:
    if language == "zh-CN":
        translated = detail.get("translatedData")
        if isinstance(translated, dict):
            for key in keys:
                value = translated.get(key)
                if isinstance(value, str):
                    text = value.strip()
                    if text:
                        return text
    for key in keys:
        value = detail.get(key)
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
    return None


def _merge_detail_into_item(item: dict[str, Any], detail: dict[str, Any], *, language: str) -> dict[str, Any]:
    enriched = dict(item)
    metadata = dict(enriched.get("metadata") or {})

    detail_title = _pick_detail_value(detail, language, "title")
    detail_subtitle = _pick_detail_value(detail, language, "subTitle", "summary")
    detail_content = _pick_detail_value(detail, language, "bodyTextOnly", "body", "content", "summary", "subTitle")

    if detail_title and len(detail_title) >= len(str(enriched.get("title") or "")):
        enriched["title"] = detail_title
    if detail_content:
        enriched["content"] = detail_content
        enriched["excerpt"] = detail_content[:280] or None
    elif detail_subtitle and not enriched.get("content"):
        enriched["content"] = detail_subtitle
        enriched["excerpt"] = detail_subtitle[:280] or None

    author_id = _first_string(detail, "squareUid") or enriched.get("author_id")
    author_name = _first_string(detail, "displayName") or enriched.get("author_name")
    author_handle = _first_string(detail, "username") or enriched.get("author_handle")
    author_verification_type = _safe_int(detail.get("authorVerificationType"))
    role_code = _safe_int(detail.get("roleCode"))
    if author_id:
        enriched["author_id"] = author_id
    if author_name:
        enriched["author_name"] = author_name
    if author_handle:
        enriched["author_handle"] = author_handle
    if (author_verification_type or 0) > 0 or (role_code or 0) != 0:
        enriched["is_kol"] = 1

    published_at = _to_millis(
        detail.get("firstReleaseTime")
        or detail.get("latestReleaseTime")
        or detail.get("createTime")
        or detail.get("updateTime")
        or detail.get("date")
    )
    if published_at is not None:
        enriched["published_at"] = published_at

    url = _first_string(detail, "webLink", "shareLink")
    if url and url.startswith("/"):
        url = urljoin(BASE, url)
    if url:
        enriched["url"] = url

    enriched["item_type"] = _resolve_item_type(detail)
    enriched["engagement"] = {
        "likes": _safe_int(detail.get("likeCount")),
        "comments": _safe_int(detail.get("commentCount")),
        "views": _safe_int(detail.get("viewCount")),
        "shares": _safe_int(detail.get("shareCount")),
        "quotes": _safe_int(detail.get("quoteCount")),
    }
    text = " ".join(
        part for part in [str(enriched.get("title") or ""), str(enriched.get("content") or "")] if part
    )
    enriched["symbols"] = _merge_lists(
        [str(symbol) for symbol in enriched.get("symbols", []) if isinstance(symbol, str)],
        _extract_symbols(detail, text),
    )
    enriched["tags"] = _merge_lists(
        [str(tag) for tag in enriched.get("tags", []) if isinstance(tag, str)],
        _extract_tags(detail),
    )

    user_labels = detail.get("userLabels")
    metadata.update(
        {
            "detail_fetched": True,
            "detail_content_type": _safe_int(detail.get("contentType")),
            "detail_author_verification_type": author_verification_type,
            "detail_role_code": role_code,
            "detail_bookmark_count": _safe_int(detail.get("bookmarkCount")),
            "detail_tipping_count": _safe_int(detail.get("tippingCount")),
            "detail_tipping_total_amount": detail.get("tippingTotalAmount"),
            "detail_has_translated_data": isinstance(detail.get("translatedData"), dict),
            "detail_detected_lang": _first_string(detail, "detectedLang", "lan"),
            "detail_user_tag": (detail.get("userTag") or {}).get("name") if isinstance(detail.get("userTag"), dict) else None,
            "detail_user_labels": [
                label.get("name")
                for label in user_labels
                if isinstance(label, dict) and isinstance(label.get("name"), str) and label.get("name").strip()
            ] if isinstance(user_labels, list) else [],
            "detail_source_mode": "api",
        }
    )
    enriched["metadata"] = metadata
    return enriched


async def _fetch_detail(content_id: str, *, language: str, referer_url: str | None) -> dict[str, Any] | None:
    data = await fetch_json(
        f"{DEFAULT_DETAIL_URL}/{content_id}",
        headers=_build_headers(language, referer=referer_url),
    )
    if not isinstance(data, dict):
        return None
    code = str(data.get("code") or "")
    if code and code != "000000":
        message = str(data.get("message") or "unknown error")
        raise ValueError(f"Binance Square detail API error {code}: {message}")
    payload = data.get("data")
    if isinstance(payload, dict):
        return payload
    return None


async def _enrich_items_with_details(items: list[dict[str, Any]], *, language: str) -> list[dict[str, Any]]:
    output = [dict(item) for item in items]
    candidates = [
        (index, item)
        for index, item in enumerate(output)
        if _should_enrich_item(item) and str((item.get("metadata") or {}).get("raw_id") or "").strip()
    ][:MAX_DETAIL_ENRICH]
    if not candidates:
        return output

    async def enrich_one(index: int, item: dict[str, Any]) -> tuple[int, dict[str, Any] | None, str | None]:
        raw_id = str((item.get("metadata") or {}).get("raw_id") or "").strip()
        try:
            detail = await _fetch_detail(raw_id, language=language, referer_url=str(item.get("url") or "") or None)
            if not detail:
                return index, None, None
            return index, _merge_detail_into_item(item, detail, language=language), None
        except Exception as exc:
            return index, None, str(exc)

    results = await asyncio.gather(*(enrich_one(index, item) for index, item in candidates))
    for index, enriched, error in results:
        if enriched is not None:
            output[index] = enriched
            continue
        metadata = dict(output[index].get("metadata") or {})
        metadata["detail_error"] = error
        output[index]["metadata"] = metadata
    return output


@cached(ttl=180, prefix="square_source_binance")
async def get_square_content(
    *,
    language: str = "en",
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    resolved_language = _normalize_language(language)
    page_size = max(1, min(limit, MAX_PAGE_SIZE))
    page_index = _normalize_page_index(cursor)
    feed_url = settings.binance_square_feed_url.strip() or DEFAULT_FEED_URL

    data = await fetch_json_post(
        feed_url,
        json_body={
            "pageIndex": page_index,
            "pageSize": page_size,
            "scene": "web-homepage",
            "contentIds": [],
        },
        headers=_build_headers(resolved_language),
    )

    if isinstance(data, dict):
        code = str(data.get("code") or "")
        if code and code != "000000":
            message = str(data.get("message") or "unknown error")
            raise ValueError(f"Binance Square API error {code}: {message}")

    raw_items = []
    if isinstance(data, dict):
        payload = data.get("data")
        if isinstance(payload, dict) and isinstance(payload.get("vos"), list):
            raw_items = payload.get("vos") or []

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in raw_items:
        if not isinstance(candidate, dict):
            continue
        normalized = _normalize_item(candidate, language=resolved_language)
        if normalized is None:
            continue
        key = str(normalized.get("external_id") or normalized.get("url") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        items.append(normalized)

    items = await _enrich_items_with_details(items, language=resolved_language)
    items.sort(key=lambda item: int(item.get("published_at") or 0), reverse=True)
    return {
        "platform": "binance",
        "channel": "square",
        "language": resolved_language,
        "source_mode": "api",
        "items": items[:page_size],
        "count": min(len(items), page_size),
        "next_cursor": str(page_index + 1) if len(raw_items) >= page_size else None,
    }
