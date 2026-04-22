"""Helpers for localizing OKX news detail into concise Chinese."""

from __future__ import annotations

import json
import logging
import re
from hashlib import sha1
from typing import Any

from app.common.ai_client import ai_chat
from app.common.cache import cache_get, cache_set
from app.config import settings

logger = logging.getLogger("bitinfo.news.translation")

_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def _normalize_language(language: str | None) -> str:
    normalized = (language or "zh-CN").strip().lower().replace("_", "-")
    if normalized.startswith("zh"):
        return "zh-CN"
    return "en-US"


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


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
