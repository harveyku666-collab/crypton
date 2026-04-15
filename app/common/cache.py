"""Redis cache abstraction with TTL decorator."""

from __future__ import annotations

import json
import functools
import logging
from typing import Any, Callable

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger("bitinfo.cache")

_pool: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _pool
    if _pool is None:
        _pool = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _pool


async def close_redis() -> None:
    global _pool
    if _pool:
        await _pool.aclose()  # type: ignore[attr-defined]
        _pool = None


async def cache_get(key: str) -> Any | None:
    r = await get_redis()
    val = await r.get(key)
    if val is not None:
        return json.loads(val)
    return None


async def cache_set(key: str, value: Any, ttl: int = 60) -> None:
    r = await get_redis()
    await r.setex(key, ttl, json.dumps(value, default=str))


def cached(ttl: int = 60, prefix: str = ""):
    """Decorator that caches the return value of an async function in Redis."""

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            key_parts = [prefix or fn.__module__, fn.__qualname__]
            if args:
                key_parts.extend(str(a) for a in args)
            if kwargs:
                key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
            cache_key = ":".join(key_parts)

            try:
                hit = await cache_get(cache_key)
                if hit is not None:
                    return hit
            except Exception:
                logger.debug("Cache read failed for %s", cache_key, exc_info=True)

            result = await fn(*args, **kwargs)

            try:
                await cache_set(cache_key, result, ttl)
            except Exception:
                logger.debug("Cache write failed for %s", cache_key, exc_info=True)

            return result

        return wrapper

    return decorator
