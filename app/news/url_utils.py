"""Helpers for normalizing external news source URLs."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin, urlparse

AICOIN_BASE = "https://www.aicoin.com"
OKX_BASE = "https://www.okx.com"


def normalize_news_source_url(url: Any, *, source: str | None = None) -> str | None:
    raw = str(url or "").strip()
    if not raw:
        return None
    if raw.startswith("//"):
        return f"https:{raw}"

    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"}:
        return raw

    normalized_source = str(source or "").strip().lower()
    if normalized_source in {"desk3", "aicoin"}:
        return urljoin(AICOIN_BASE, raw)
    if normalized_source in {"okx", "okx_orbit"}:
        return urljoin(OKX_BASE, raw)
    return raw
