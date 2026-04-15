"""Shared async HTTP client with connection pooling, retry, timeout, and outbound whitelist.

Security:
  - All outbound requests are checked against ALLOWED_HOSTS from endpoints.py
  - Requests to unknown hosts are blocked and logged as security events
  - Only GET requests go through fetch_json; no user data is sent via query params
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("bitinfo.http")
security_logger = logging.getLogger("bitinfo.security")

_client: httpx.AsyncClient | None = None

DEFAULT_TIMEOUT = 15.0
MAX_RETRIES = 3
BACKOFF_BASE = 0.5


def _check_host_allowed(url: str) -> None:
    """Block requests to hosts not registered in endpoints.py."""
    from app.common.endpoints import ALLOWED_HOSTS
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host and host not in ALLOWED_HOSTS:
        security_logger.error(
            "BLOCKED outbound request to unregistered host: %s (url=%s)", host, url
        )
        raise PermissionError(
            f"Outbound request blocked: host '{host}' is not in the allowed whitelist. "
            f"Register it in app/common/endpoints.py first."
        )


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            follow_redirects=True,
        )
    return _client


async def close_client() -> None:
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None


async def fetch_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int = MAX_RETRIES,
) -> Any:
    """GET JSON from url. Host must be registered in endpoints.py."""
    _check_host_allowed(url)

    client = await get_client()
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPStatusError, httpx.ConnectError, httpx.ReadTimeout) as exc:
            last_exc = exc
            if attempt < retries - 1:
                wait = BACKOFF_BASE * (2 ** attempt)
                logger.warning("Retry %d for %s: %s (wait %.1fs)", attempt + 1, url, exc, wait)
                await asyncio.sleep(wait)
    raise last_exc  # type: ignore[misc]
