"""OKX Orbit news and sentiment helpers.

These endpoints mirror the OKX CLI/MCP public intelligence layer for news,
article search, and coin sentiment. They intentionally avoid any trading
actions and only expose data that is useful for analysis pages.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Any

from app.config import settings

from app.common.cache import cached
from app.common.http_client import fetch_json
from app.news.url_utils import normalize_news_source_url

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    tomllib = None

BASE = "https://www.okx.com/api/v5/orbit"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
NEWS_IMPORTANCE = {"high", "low"}
NEWS_SENTIMENT = {"bullish", "bearish", "neutral"}
NEWS_SORT = {"latest", "relevant"}
SENTIMENT_PERIODS = {"1h", "4h", "24h"}
DETAIL_LEVELS = {"brief", "summary", "full"}
OKX_NEWS_SOURCES = {"auto", "orbit", "cli"}

logger = logging.getLogger("bitinfo.okx.news")
_OKX_BIN: str | None = None


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


def _resolve_news_source() -> str:
    raw = str(getattr(settings, "okx_news_source", "auto") or "auto").strip().lower()
    return raw if raw in OKX_NEWS_SOURCES else "auto"


def _find_okx() -> str:
    global _OKX_BIN
    if _OKX_BIN:
        return _OKX_BIN
    candidate = shutil.which("okx")
    if candidate:
        _OKX_BIN = candidate
        return candidate
    raise FileNotFoundError("okx CLI not found")


def _load_okx_cli_config() -> dict[str, Any]:
    path = Path.home() / ".okx" / "config.toml"
    if not path.exists() or tomllib is None:
        return {}
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _resolve_okx_cli_profile() -> tuple[str | None, bool | None]:
    configured = str(getattr(settings, "okx_cli_profile", "") or "").strip()
    config = _load_okx_cli_config()
    if configured:
        section = config.get(configured)
        demo = bool(section.get("demo")) if isinstance(section, dict) else None
        return configured, demo
    default_profile = config.get("default_profile")
    if isinstance(default_profile, str) and default_profile.strip():
        section = config.get(default_profile)
        demo = bool(section.get("demo")) if isinstance(section, dict) else None
        return default_profile.strip(), demo
    return None, None


def _should_try_cli_news() -> bool:
    source = _resolve_news_source()
    if source == "orbit":
        return False
    profile, demo = _resolve_okx_cli_profile()
    force_live = bool(getattr(settings, "okx_cli_live", False))
    if source == "cli":
        return True
    if profile and demo is False:
        return True
    if profile and force_live:
        return True
    return False


async def _run_okx_cli_json(*args: str, timeout: float = 20.0) -> Any:
    cmd = [_find_okx()]
    profile, _demo = _resolve_okx_cli_profile()
    if profile:
        cmd.extend(["--profile", profile])
    if bool(getattr(settings, "okx_cli_live", False)):
        cmd.append("--live")
    cmd.extend(args)
    cmd.append("--json")
    logger.debug("okx cli cmd: %s", " ".join(cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    raw_stdout = stdout.decode().strip() if stdout else ""
    raw_stderr = stderr.decode().strip() if stderr else ""
    if proc.returncode != 0:
        raise RuntimeError(raw_stderr or raw_stdout or f"okx cli exited {proc.returncode}")
    if not raw_stdout:
        return None
    return json.loads(raw_stdout)


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


def _cli_page(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        return data
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return {}


def _normalize_cli_article(item: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_article(item)
    platforms = item.get("platformList") if isinstance(item.get("platformList"), list) else []
    primary_source = str(platforms[0] or "okx").strip().lower() if platforms else "okx"
    normalized["source_url"] = normalize_news_source_url(item.get("sourceUrl"), source=primary_source)
    normalized["source"] = "okx_cli_news"
    return normalized


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
        "backend": "okx_orbit_public",
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


def _normalize_cli_news_page(
    data: Any,
    *,
    language: str,
    kind: str,
) -> dict[str, Any]:
    page = _cli_page(data)
    details = page.get("details") if isinstance(page.get("details"), list) else []
    return {
        "kind": kind,
        "language": _normalize_language(language),
        "items": [_normalize_cli_article(item) for item in details if isinstance(item, dict)],
        "count": len(details),
        "next_cursor": page.get("nextCursor"),
        "warning": None,
        "code": "0",
        "msg": "",
        "backend": "okx_cli",
    }


def _normalize_cli_sentiment_page(data: Any, *, period: str, sort_by: str | None = None) -> dict[str, Any]:
    page = _cli_page(data)
    details = page.get("details") if isinstance(page.get("details"), list) else []
    payload = {
        "period": period,
        "items": [_normalize_sentiment_item(item) for item in details if isinstance(item, dict)],
        "count": len(details),
        "code": "0",
        "msg": "",
        "warning": None,
        "backend": "okx_cli",
    }
    if sort_by is not None:
        payload["sort_by"] = sort_by
    return payload


def _normalize_cli_detail_payload(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        article = data if isinstance(data.get("id"), (str, int)) else None
    elif isinstance(data, list) and data and isinstance(data[0], dict):
        article = data[0]
    else:
        article = None
    return {
        "item": _normalize_cli_article(article) if isinstance(article, dict) else None,
        "code": "0",
        "msg": "",
        "warning": None,
        "backend": "okx_cli",
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
    if _should_try_cli_news():
        try:
            payload = await _run_okx_cli_json(
                "news",
                "latest",
                *(["--coins", coins] if coins else []),
                *(["--importance", resolved_importance] if resolved_importance else []),
                *(["--platform", platform] if platform else []),
                *(["--begin", str(begin)] if begin is not None else []),
                *(["--end", str(end)] if end is not None else []),
                "--lang", _normalize_language(language),
                "--detail-lvl", resolved_detail,
                "--limit", str(min(max(limit, 1), 50)),
                *(["--after", after] if after else []),
            )
            return _normalize_cli_news_page(payload, language=language, kind="latest")
        except Exception as exc:
            logger.warning("okx cli latest news failed, falling back to public orbit: %s", exc)
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
    if _should_try_cli_news():
        try:
            payload = await _run_okx_cli_json(
                "news",
                "by-coin",
                "--coins", coins.upper(),
                *(["--importance", resolved_importance] if resolved_importance else []),
                *(["--platform", platform] if platform else []),
                *(["--begin", str(begin)] if begin is not None else []),
                *(["--end", str(end)] if end is not None else []),
                "--lang", _normalize_language(language),
                "--detail-lvl", resolved_detail,
                "--limit", str(min(max(limit, 1), 50)),
            )
            return _normalize_cli_news_page(payload, language=language, kind="coin")
        except Exception as exc:
            logger.warning("okx cli coin news failed, falling back to public orbit: %s", exc)
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
    if _should_try_cli_news():
        try:
            payload = await _run_okx_cli_json(
                "news",
                "search",
                *(["--keyword", keyword] if keyword else []),
                *(["--coins", coins.upper()] if isinstance(coins, str) and coins else []),
                *(["--importance", resolved_importance] if resolved_importance else []),
                *(["--platform", platform] if platform else []),
                *(["--sentiment", resolved_sentiment] if resolved_sentiment else []),
                *(["--sort-by", resolved_sort] if resolved_sort else []),
                *(["--begin", str(begin)] if begin is not None else []),
                *(["--end", str(end)] if end is not None else []),
                "--lang", _normalize_language(language),
                "--detail-lvl", resolved_detail,
                "--limit", str(min(max(limit, 1), 50)),
                *(["--after", after] if after else []),
            )
            return _normalize_cli_news_page(payload, language=language, kind="search")
        except Exception as exc:
            logger.warning("okx cli news search failed, falling back to public orbit: %s", exc)
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
    if _should_try_cli_news():
        try:
            payload = await _run_okx_cli_json(
                "news",
                "detail",
                article_id,
                "--lang", _normalize_language(language),
            )
            return _normalize_cli_detail_payload(payload)
        except Exception as exc:
            logger.warning("okx cli news detail failed, falling back to public orbit: %s", exc)
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
        "backend": "okx_orbit_public",
    }


@cached(ttl=1800, prefix="okx_news_platforms")
async def get_news_platforms() -> dict[str, Any]:
    if _should_try_cli_news():
        try:
            payload = await _run_okx_cli_json("news", "platforms")
            items = payload if isinstance(payload, list) else []
            return {
                "items": [str(item) for item in items if item],
                "count": len(items),
                "code": "0",
                "msg": "",
                "warning": None,
                "backend": "okx_cli",
            }
        except Exception as exc:
            logger.warning("okx cli news platforms failed, falling back to public orbit: %s", exc)
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
        "backend": "okx_orbit_public",
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
    if _should_try_cli_news():
        try:
            action = "coin-trend" if include_trend else "coin-sentiment"
            payload = await _run_okx_cli_json(
                "news",
                action,
                *(["--coins", coins.upper()] if action == "coin-trend" else ["--coins", coins.upper()]),
                "--period", "1h" if include_trend and resolved_period == "24h" else resolved_period,
                *(["--points", str(min(max(trend_points or 0, 1), 48))] if include_trend else []),
            )
            return _normalize_cli_sentiment_page(payload, period=resolved_period)
        except Exception as exc:
            logger.warning("okx cli coin sentiment failed, falling back to public orbit: %s", exc)
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
        "backend": "okx_orbit_public",
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
    if _should_try_cli_news():
        try:
            cli_sort = {"hot": "0", "bullish": "1", "bearish": "2"}.get(resolved_sort, "0")
            payload = await _run_okx_cli_json(
                "news",
                "sentiment-rank",
                "--period", resolved_period,
                "--sort-by", cli_sort,
                "--limit", str(min(max(limit, 1), 50)),
            )
            return _normalize_cli_sentiment_page(payload, period=resolved_period, sort_by=resolved_sort)
        except Exception as exc:
            logger.warning("okx cli sentiment ranking failed, falling back to public orbit: %s", exc)
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
        "backend": "okx_orbit_public",
    }
