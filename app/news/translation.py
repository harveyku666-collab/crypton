"""Helpers for localizing OKX news detail into concise Chinese."""

from __future__ import annotations

import html
import json
import logging
import re
from hashlib import sha1
from typing import Any

from app.common.ai_client import ai_chat
from app.common.cache import cache_get, cache_set
from app.common.http_client import fetch_bytes
from app.config import settings

logger = logging.getLogger("bitinfo.news.translation")

_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_PUBLIC_FEED_RE = re.compile(r"^https://www\.okx\.com/[a-z]{2}(?:-[a-z]{2,8})?/feed/post/\d+$", re.IGNORECASE)
_APP_STATE_RE = re.compile(
    r'<script[^>]+data-id="__app_data_for_ssr__"[^>]+id="appState"[^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _normalize_language(language: str | None) -> str:
    normalized = (language or "zh-CN").strip().lower().replace("_", "-")
    if normalized.startswith("zh"):
        return "zh-CN"
    return "en-US"


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_rich_text(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    text = _HTML_TAG_RE.sub("", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _needs_zh_translation(text: str) -> bool:
    if not text:
        return False
    cjk_count = len(_CJK_RE.findall(text))
    latin_count = len(_LATIN_RE.findall(text))
    if latin_count < 8:
        return False
    if cjk_count == 0:
        return True
    return latin_count > cjk_count * 3


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if line.strip("`").strip()]
        if lines and lines[0].strip().lower().startswith("```json"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        data = json.loads(text[start:end + 1])
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _translation_cache_key(*, article_id: str, title: str, summary: str, content: str) -> str:
    digest = sha1(
        json.dumps(
            {
                "article_id": article_id,
                "title": title,
                "summary": summary,
                "content": content[:1800],
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return f"okx_news_translate_zh:{article_id or 'unknown'}:{digest}"


async def _translate_article_brief_to_zh(
    *,
    article_id: str,
    title: str,
    summary: str,
    content: str,
) -> dict[str, str]:
    if not settings.openai_api_key:
        return {}

    cache_key = _translation_cache_key(
        article_id=article_id,
        title=title,
        summary=summary,
        content=content,
    )
    try:
        cached = await cache_get(cache_key)
        if isinstance(cached, dict):
            return {key: str(value).strip() for key, value in cached.items() if str(value or "").strip()}
    except Exception:
        logger.debug("news translation cache read failed for %s", cache_key, exc_info=True)

    system_prompt = (
        "You are a crypto news editor translating article details for a Chinese UI. "
        "Translate into concise Simplified Chinese. Preserve coin tickers, project names, "
        "numbers, prices, dates, and percentages. Do not invent facts or add commentary. "
        "Return strict JSON with keys: title, summary, content. "
        "summary should be one short paragraph under 90 Chinese characters. "
        "content should be 2-4 short Chinese sentences summarizing the key facts, under 220 Chinese characters total."
    )
    user_message = json.dumps(
        {
            "title": title,
            "summary": summary,
            "content": content[:1800],
        },
        ensure_ascii=False,
    )
    try:
        raw = await ai_chat(system_prompt, user_message, temperature=0.1, max_tokens=500)
        parsed = _parse_json_object(raw)
    except Exception:
        logger.warning("news translation request failed for article %s", article_id or "unknown", exc_info=True)
        return {}

    translated = {
        "translated_title": _clean_text(parsed.get("title")),
        "translated_summary": _clean_text(parsed.get("summary")),
        "translated_content": _clean_text(parsed.get("content")),
    }
    translated = {key: value for key, value in translated.items() if value}
    if not translated:
        return {}

    try:
        await cache_set(cache_key, translated, ttl=86400)
    except Exception:
        logger.debug("news translation cache write failed for %s", cache_key, exc_info=True)
    return translated


async def _load_public_feed_translation(source_url: str, *, language: str) -> dict[str, str]:
    if not source_url or not _PUBLIC_FEED_RE.match(source_url):
        return {}

    cache_key = f"okx_public_feed_translation:{_normalize_language(language)}:{sha1(source_url.encode('utf-8')).hexdigest()}"
    try:
        cached = await cache_get(cache_key)
        if isinstance(cached, dict):
            return {key: str(value).strip() for key, value in cached.items() if str(value or "").strip()}
    except Exception:
        logger.debug("public feed translation cache read failed for %s", cache_key, exc_info=True)

    preferred_url = source_url
    if _normalize_language(language) == "zh-CN":
        preferred_url = re.sub(
            r"/[a-z]{2}(?:-[a-z]{2,8})?/feed/post/",
            "/zh-hans/feed/post/",
            source_url,
            count=1,
            flags=re.IGNORECASE,
        )
    try:
        body, _ = await fetch_bytes(
            preferred_url,
            headers={"User-Agent": "Mozilla/5.0", "Accept-Language": _normalize_language(language)},
        )
        html_text = body.decode("utf-8", errors="ignore")
    except Exception:
        logger.debug("failed to load public feed translation for %s", preferred_url, exc_info=True)
        return {}

    match = _APP_STATE_RE.search(html_text)
    if not match:
        return {}
    try:
        payload = json.loads(match.group(1))
    except Exception:
        return {}

    detail = (
        (((payload.get("appContext") or {}).get("initialProps") or {}).get("contentDetail"))
        if isinstance(payload, dict)
        else None
    )
    if not isinstance(detail, dict):
        return {}

    content_list = detail.get("contentList") if isinstance(detail.get("contentList"), list) else []
    content_parts: list[str] = []
    for row in content_list:
        if not isinstance(row, dict):
            continue
        content = row.get("translatedContent") or row.get("content")
        text = _clean_rich_text(content)
        if text:
            content_parts.append(text)

    translated = {
        "translated_title": _clean_rich_text(detail.get("title") or detail.get("enTitle")),
        "translated_summary": _clean_rich_text(detail.get("summary")),
        "translated_content": "\n\n".join(part for part in content_parts if part).strip(),
    }
    translated = {key: value for key, value in translated.items() if value}
    if not translated:
        return {}

    translated["translation_mode"] = "okx_public_feed"
    try:
        await cache_set(cache_key, translated, ttl=86400)
    except Exception:
        logger.debug("public feed translation cache write failed for %s", cache_key, exc_info=True)
    return translated


async def localize_article_for_language(item: dict[str, Any], *, language: str | None) -> dict[str, Any]:
    if not isinstance(item, dict):
        return item
    if _normalize_language(language) != "zh-CN":
        return item

    title = _clean_text(item.get("title"))
    summary = _clean_text(item.get("summary") or item.get("excerpt"))
    content = _clean_text(item.get("content") or summary)
    if not _needs_zh_translation(title) and not _needs_zh_translation(content or summary):
        return item

    source_url = _clean_text(item.get("source_url"))
    public_feed_translation = await _load_public_feed_translation(source_url, language=language or "zh-CN")
    if public_feed_translation:
        localized = dict(item)
        localized.update(public_feed_translation)
        return localized

    translated = await _translate_article_brief_to_zh(
        article_id=_clean_text(item.get("id")),
        title=title,
        summary=summary,
        content=content,
    )
    if not translated:
        return item

    localized = dict(item)
    localized.update(translated)
    localized["translation_mode"] = "zh_key_points"
    return localized
