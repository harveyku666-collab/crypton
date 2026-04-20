"""OKX square/feed content adapters.

Priority order:
1. OKX Orbit API, when available.
2. Configured public OKX Feed post pages as a fallback when Orbit is app-only.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urlparse

from app.common.cache import cached
from app.common.http_client import fetch_bytes
from app.config import settings
from app.news import okx_orbit

PUBLIC_FEED_POST_RE = re.compile(r"https://www\.okx\.com/[a-z]{2}(?:-[a-z]{2})?/feed/post/(\d+)", re.IGNORECASE)
APP_STATE_RE = re.compile(
    r'<script[^>]+data-id="__app_data_for_ssr__"[^>]+id="appState"[^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def _normalize_language(language: str | None) -> str:
    normalized = (language or "zh-CN").strip().lower().replace("_", "-")
    if normalized.startswith("zh"):
        return "zh-CN"
    return "en-US"


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except Exception:
        return None


def _make_external_id(item: dict[str, Any]) -> str:
    raw_id = item.get("id")
    if raw_id not in (None, ""):
        return f"okx_{raw_id}"
    seed = "|".join(
        part
        for part in [
            str(item.get("source_url") or ""),
            str(item.get("title") or ""),
            str(item.get("published_at") or ""),
        ]
        if part
    )
    return f"okx_{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:24]}"


def _configured_public_feed_urls() -> list[str]:
    raw = settings.okx_public_feed_urls.strip()
    if not raw:
        return []
    seen: set[str] = set()
    urls: list[str] = []
    for part in re.split(r"[\n,\s]+", raw):
        candidate = part.strip()
        if not candidate or candidate in seen:
            continue
        if PUBLIC_FEED_POST_RE.match(candidate):
            seen.add(candidate)
            urls.append(candidate)
    return urls


def _extract_author_handle(detail: dict[str, Any]) -> str | None:
    source = detail.get("source") if isinstance(detail.get("source"), dict) else {}
    source_url = source.get("url") if isinstance(source.get("url"), str) else None
    if not source_url:
        return None
    parsed = urlparse(source_url)
    if parsed.netloc.endswith("x.com") or parsed.netloc.endswith("twitter.com"):
        parts = [part for part in parsed.path.split("/") if part]
        if parts:
            return parts[0].lstrip("@") or None
    return None


def _extract_hash_tags(tag_list: dict[str, Any] | None) -> list[str]:
    if not isinstance(tag_list, dict):
        return []
    tags = tag_list.get("hashTagList")
    if not isinstance(tags, list):
        return []
    output: list[str] = []
    seen: set[str] = set()
    for row in tags:
        value = None
        if isinstance(row, dict):
            value = row.get("tagName") or row.get("name") or row.get("tag")
        elif isinstance(row, str):
            value = row
        if not isinstance(value, str):
            continue
        cleaned = value.strip().lstrip("#").strip()
        if not cleaned:
            continue
        marker = cleaned.lower()
        if marker in seen:
            continue
        seen.add(marker)
        output.append(cleaned)
    return output


def _extract_feed_tokens(detail: dict[str, Any]) -> list[str]:
    tokens = detail.get("tokens")
    if not isinstance(tokens, list):
        return []
    output: list[str] = []
    seen: set[str] = set()
    for row in tokens:
        token = None
        if isinstance(row, dict):
            token = row.get("coinName")
            if not token:
                inst_id = str(row.get("instId") or "")
                if "-" in inst_id:
                    token = inst_id.split("-", 1)[0]
        elif isinstance(row, str):
            token = row
        if not isinstance(token, str):
            continue
        cleaned = token.strip().upper()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        output.append(cleaned)
    return output


def _normalize_public_feed_item(url: str, html_text: str, *, language: str) -> dict[str, Any] | None:
    match = APP_STATE_RE.search(html_text)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except Exception:
        return None
    detail = (
        (((payload.get("appContext") or {}).get("initialProps") or {}).get("contentDetail"))
        if isinstance(payload, dict)
        else None
    )
    if not isinstance(detail, dict):
        return None
    author = detail.get("author") if isinstance(detail.get("author"), dict) else {}
    content_list = detail.get("contentList") if isinstance(detail.get("contentList"), list) else []
    raw_id = None
    content_parts: list[str] = []
    image_urls: list[str] = []
    published_at = None
    for row in content_list:
        if not isinstance(row, dict):
            continue
        if raw_id is None and row.get("contentId") not in (None, ""):
            raw_id = str(row.get("contentId"))
        content = row.get("translatedContent") or row.get("content")
        if isinstance(content, str) and content.strip():
            content_parts.append(content.strip())
        publish_time = _safe_int(row.get("publishTime"))
        if publish_time is not None:
            published_at = max(published_at or 0, publish_time)
        image_list = row.get("imageList")
        if isinstance(image_list, list):
            for image in image_list:
                if isinstance(image, dict) and isinstance(image.get("url"), str):
                    image_urls.append(image["url"])

    title = str(detail.get("title") or detail.get("enTitle") or "").strip() or None
    content = "\n\n".join(part for part in content_parts if part) or None
    summary = str(detail.get("summary") or "").strip() or None
    author_name = str(author.get("nickName") or "").strip() or None
    author_id = str(author.get("authorId") or "").strip() or None
    author_handle = _extract_author_handle(detail)
    official_status = _safe_int(author.get("officialStatus")) or 0
    author_type = _safe_int(author.get("type")) or 0
    is_native_kol = official_status > 0 or author_type > 1

    item = {
        "id": raw_id,
        "title": title,
        "summary": summary,
        "content": content,
        "excerpt": (content or summary or title or "")[:280] or None,
        "source_url": url,
        "platforms": ["okx_feed_public"],
        "coins": _extract_feed_tokens(detail),
        "importance": None,
        "sentiment": None,
        "published_at": published_at,
        "source": "okx_feed_public",
    }
    return {
        "external_id": _make_external_id(item),
        "platform": "okx",
        "channel": "square",
        "item_type": "post",
        "title": title,
        "content": content or summary,
        "excerpt": item["excerpt"],
        "author_id": author_id,
        "author_name": author_name,
        "author_handle": author_handle,
        "is_kol": 1 if is_native_kol else 0,
        "matched_kol_name": author_name if is_native_kol else None,
        "matched_kol_handle": author_handle if is_native_kol else None,
        "matched_kol_tier": "platform_native" if is_native_kol else None,
        "language": language,
        "published_at": published_at,
        "url": url,
        "engagement": {
            "likes": _safe_int(detail.get("likeCount")),
            "comments": _safe_int(detail.get("commentNum")),
            "views": _safe_int(detail.get("viewNum")),
            "shares": _safe_int(detail.get("shareNum")),
        },
        "symbols": item["coins"],
        "tags": _extract_hash_tags(content_list[0].get("tagList") if content_list and isinstance(content_list[0], dict) else detail.get("tagList")),
        "metadata": {
            "source_mode": "public_feed_page",
            "source_platform": (detail.get("source") or {}).get("platform") if isinstance(detail.get("source"), dict) else None,
            "source_url": (detail.get("source") or {}).get("url") if isinstance(detail.get("source"), dict) else None,
            "official_status": official_status,
            "author_type": author_type,
            "format_type": _safe_int(detail.get("formatType")),
            "category": _safe_int(detail.get("category")),
            "image_urls": image_urls[:6],
        },
    }


async def _load_public_feed_items(
    urls: list[str],
    *,
    language: str,
    limit: int,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for url in urls:
        if len(items) >= limit:
            break
        try:
            body, _ = await fetch_bytes(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": language})
        except Exception:
            continue
        text = body.decode("utf-8", errors="ignore")
        item = _normalize_public_feed_item(url, text, language=language)
        if item is None:
            continue
        key = str(item.get("external_id") or item.get("url") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        items.append(item)
    items.sort(key=lambda row: int(row.get("published_at") or 0), reverse=True)
    return items[:limit]


@cached(ttl=180, prefix="square_source_okx")
async def get_square_content(
    *,
    language: str = "zh-CN",
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    resolved_language = _normalize_language(language)
    page = await okx_orbit.get_latest_news(
        language=resolved_language,
        detail_lvl="summary",
        limit=max(1, min(limit, 50)),
        after=cursor,
    )
    items: list[dict[str, Any]] = []
    for article in page.get("items", []):
        if not isinstance(article, dict):
            continue
        title = str(article.get("title") or "").strip() or None
        content = str(article.get("summary") or article.get("excerpt") or article.get("content") or "").strip() or None
        items.append(
            {
                "external_id": _make_external_id(article),
                "platform": "okx",
                "channel": "square",
                "item_type": "article",
                "title": title,
                "content": content,
                "excerpt": (content or title or "")[:280] or None,
                "author_id": None,
                "author_name": None,
                "author_handle": None,
                "language": resolved_language,
                "published_at": article.get("published_at"),
                "url": article.get("source_url"),
                "engagement": {},
                "symbols": [coin for coin in article.get("coins", []) if isinstance(coin, str) and coin],
                "tags": [platform for platform in article.get("platforms", []) if isinstance(platform, str) and platform],
                "metadata": {
                    "orbit_source": article.get("source"),
                    "platforms": article.get("platforms"),
                    "source_mode": "orbit_api",
                },
            }
        )

    warning = page.get("warning")
    source_mode = "api"
    if not items and warning:
        public_urls = _configured_public_feed_urls()
        if public_urls:
            items = await _load_public_feed_items(public_urls, language=resolved_language, limit=max(1, min(limit, 50)))
            if items:
                source_mode = "public_feed_pages"
                warning = f"{warning}; using configured public OKX Feed post fallback"
        else:
            source_mode = "app-only"

    return {
        "platform": "okx",
        "channel": "square",
        "language": resolved_language,
        "source_mode": source_mode,
        "items": items,
        "count": len(items),
        "next_cursor": page.get("next_cursor") if source_mode == "api" else None,
        "warning": warning,
    }
