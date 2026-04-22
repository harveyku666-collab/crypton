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

from app.config import settings

logger = logging.getLogger("bitinfo.http")
security_logger = logging.getLogger("bitinfo.security")

_client: httpx.AsyncClient | None = None
_proxy_client: httpx.AsyncClient | None = None
_proxy_client_url: str = ""
_warned_missing_proxy_hosts: set[str] = set()

DEFAULT_TIMEOUT = 15.0
MAX_RETRIES = 3
BACKOFF_BASE = 0.5

RESTRICTED_HOSTS = {
    "fapi.binance.com",
    "dapi.binance.com",
    "api.bybit.com",
    "api.deribit.com",
    "api.coinbase.com",
    "advanced-api.coinbase.com",
}


def _resolve_proxy_url() -> str:
    return str(
        os.environ.get("PROXY_URL")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY")
        or settings.proxy_url
        or ""
    ).strip()


def _mask_proxy_url(proxy_url: str) -> str:
    if not proxy_url:
        return ""
    parsed = urlparse(proxy_url)
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    if parsed.scheme and host:
        return f"{parsed.scheme}://{host}{port}"
    return proxy_url.split("@")[-1]


def get_proxy_status() -> dict[str, Any]:
    proxy_url = _resolve_proxy_url()
    return {
        "configured": bool(proxy_url),
        "url": _mask_proxy_url(proxy_url),
        "restricted_hosts": sorted(RESTRICTED_HOSTS),
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
    global _proxy_client, _proxy_client_url
    proxy_url = _resolve_proxy_url()
    if not proxy_url:
        return None
    if _proxy_client is not None and ( _proxy_client.is_closed or _proxy_client_url != proxy_url):
        await _proxy_client.aclose()
        _proxy_client = None
        _proxy_client_url = ""
    if _proxy_client is None:
        _proxy_client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
            follow_redirects=True,
            proxy=proxy_url,
        )
        _proxy_client_url = proxy_url
        logger.info("Proxy client initialized: %s", _mask_proxy_url(proxy_url))
    return _proxy_client


async def _select_client(url: str) -> httpx.AsyncClient:
    use_proxy = _needs_proxy(url)
    if use_proxy:
        client = await get_proxy_client()
        if client is None:
            host = urlparse(url).hostname or ""
            if host not in _warned_missing_proxy_hosts:
                logger.warning(
                    "No proxy configured for restricted host: %s. "
                    "Configure PROXY_URL in .env or the service environment.",
                    host,
                )
                _warned_missing_proxy_hosts.add(host)
            return await get_client()
        return client
    return await get_client()


async def close_client() -> None:
    global _client, _proxy_client, _proxy_client_url
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None
    if _proxy_client and not _proxy_client.is_closed:
        await _proxy_client.aclose()
        _proxy_client = None
    _proxy_client_url = ""
    _warned_missing_proxy_hosts.clear()


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
    client = await _select_client(url)

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


async def _request_bytes(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int = MAX_RETRIES,
) -> tuple[bytes, str | None]:
    """Request raw bytes from url with shared whitelist, timeout, retry, and proxy rules."""
    _check_host_allowed(url)
    client = await _select_client(url)

    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = await client.request(method, url, params=params, headers=headers)
            resp.raise_for_status()
            return resp.content, resp.headers.get("content-type")
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


async def fetch_bytes(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int = MAX_RETRIES,
) -> tuple[bytes, str | None]:
    """GET raw bytes from url. Host must be registered in endpoints.py."""
    return await _request_bytes("GET", url, params=params, headers=headers, retries=retries)
