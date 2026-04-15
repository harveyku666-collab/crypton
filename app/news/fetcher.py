"""Multi-source news fetcher with multi-language support."""

from __future__ import annotations

import asyncio
from typing import Any

from app.common.http_client import fetch_json
from app.common.cache import cached

DESK3_API = "https://api1.desk3.io/v1"

NEWS_CATEGORIES = {"crypto": 1, "headlines": 2, "policy": 3, "flash": 4}

SUPPORTED_LANGUAGES = {
    "en": "en",
    "zh": "zh-CN",
    "ja": "ja",
    "ko": "ko",
    "es": "es",
    "fr": "fr",
    "de": "de",
    "ru": "ru",
    "pt": "pt",
    "ar": "ar",
}


@cached(ttl=300, prefix="news")
async def fetch_desk3_news(
    category: str = "crypto",
    count: int = 20,
    language: str = "en",
) -> list[dict]:
    """Fetch news from Desk3 in the specified language, with sentiment tags."""
    from app.news.sentiment import tag_news

    catid = NEWS_CATEGORIES.get(category, 1)
    lang_code = SUPPORTED_LANGUAGES.get(language, language)
    headers = {"language": lang_code}

    data = await fetch_json(
        f"{DESK3_API}/news/list",
        params={"catid": catid, "page": 1, "rows": count},
        headers=headers,
    )
    if data.get("code") != 0:
        return []
    items = data.get("data", {}).get("list", [])
    return [
        tag_news({
            "title": i.get("title", ""),
            "description": i.get("description", ""),
            "source": "desk3",
            "category": category,
            "language": language,
            "published_at": i.get("published_at"),
            "url": i.get("url"),
            "external_id": f"desk3_{catid}_{i.get('id', i.get('published_at', ''))}",
        })
        for i in items
    ]


async def fetch_all_news(language: str = "en") -> dict[str, list[dict]]:
    results = await asyncio.gather(
        fetch_desk3_news("crypto", 15, language),
        fetch_desk3_news("policy", 15, language),
        return_exceptions=True,
    )
    return {
        "crypto": results[0] if not isinstance(results[0], BaseException) else [],
        "policy": results[1] if not isinstance(results[1], BaseException) else [],
    }


async def fetch_multilang_news(
    languages: list[str] | None = None,
    categories: list[str] | None = None,
    count: int = 10,
) -> dict[str, dict[str, list[dict]]]:
    """Fetch news in multiple languages simultaneously.

    Returns: {language: {category: [items]}}
    """
    langs = languages or ["en", "zh"]
    cats = categories or ["crypto", "policy"]

    tasks = {}
    for lang in langs:
        for cat in cats:
            tasks[f"{lang}:{cat}"] = fetch_desk3_news(cat, count, lang)

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    output: dict[str, dict[str, list[dict]]] = {}
    for key, result in zip(tasks.keys(), results):
        lang, cat = key.split(":")
        if lang not in output:
            output[lang] = {}
        output[lang][cat] = result if not isinstance(result, BaseException) else []

    return output
