"""Shared async HTTP client with connection pooling, retry, timeout, and outbound whitelist.

Security:
  - All outbound requests are checked against ALLOWED_HOSTS from endpoints.py
  - Requests to unknown hosts are blocked and logged as security events
  - JSON requests go through the same host whitelist, timeout, retry, and proxy rules

Proxy:
  - Set PROXY_URL env var (e.g. socks5://127.0.0.1:7890 or http://proxy:8080)
  - Geographically restricted hosts (Binance Futures, Bybit, etc.) auto-route through proxy
  - Non-restricted hosts use direct connection for speed
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("bitinfo.http")
security_logger = logging.getLogger("bitinfo.security")

_client: httpx.AsyncClient | None = None
_proxy_client: httpx.AsyncClient | None = None

DEFAULT_TIMEOUT = 15.0
MAX_RETRIES = 3
BACKOFF_BASE = 0.5

PROXY_URL = os.environ.get("PROXY_URL") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or ""

RESTRICTED_HOSTS = {
    "fapi.binance.com",
    "dapi.binance.com",
    "api.bybit.com",
    "www.okx.com",
    "api.deribit.com",
    "api.coinbase.com",
    "advanced-api.coinbase.com",
}


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


def _needs_proxy(url: str) -> bool:
    """Check if a URL targets a geographically restricted host."""
    parsed = urlparse(url)
    return (parsed.hostname or "") in RESTRICTED_HOSTS


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            follow_redirects=True,
        )
    return _client


async def get_proxy_client() -> httpx.AsyncClient | None:
    """Return a proxy-enabled client if PROXY_URL is configured."""
    global _proxy_client
    if not PROXY_URL:
        return None
    if _proxy_client is None or _proxy_client.is_closed:
        _proxy_client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
            follow_redirects=True,
            proxy=PROXY_URL,
        )
        logger.info("Proxy client initialized: %s", PROXY_URL.split("@")[-1])
    return _proxy_client


async def close_client() -> None:
    global _client, _proxy_client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None
    if _proxy_client and not _proxy_client.is_closed:
        await _proxy_client.aclose()
        _proxy_client = None


async def _request_json(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | list[Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int = MAX_RETRIES,
) -> Any:
    """Request JSON from url with shared whitelist, retry, timeout, and proxy rules."""
    _check_host_allowed(url)

    use_proxy = _needs_proxy(url)
    if use_proxy:
        client = await get_proxy_client()
        if client is None:
            logger.warning("No proxy configured for restricted host: %s", urlparse(url).hostname)
            client = await get_client()
    else:
        client = await get_client()

    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = await client.request(method, url, params=params, json=json_body, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPStatusError, httpx.ConnectError, httpx.ReadTimeout) as exc:
            last_exc = exc
            if attempt < retries - 1:
                wait = BACKOFF_BASE * (2 ** attempt)
                logger.warning("Retry %d for %s %s: %s (wait %.1fs)", attempt + 1, method, url, exc, wait)
                await asyncio.sleep(wait)
    raise last_exc  # type: ignore[misc]


async def fetch_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int = MAX_RETRIES,
) -> Any:
    """GET JSON from url. Host must be registered in endpoints.py."""
    return await _request_json("GET", url, params=params, headers=headers, retries=retries)


async def fetch_json_post(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | list[Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int = MAX_RETRIES,
) -> Any:
    """POST JSON to url. Host must be registered in endpoints.py."""
    return await _request_json(
        "POST",
        url,
        params=params,
        json_body=json_body,
        headers=headers,
        retries=retries,
    )
