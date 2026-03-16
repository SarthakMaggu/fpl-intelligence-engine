from __future__ import annotations

import hashlib
from typing import Any

from core.config import settings
from core.redis_client import cache_get_json, cache_set_json, redis_client


def make_cache_key(prefix: str, *parts: object) -> str:
    payload = "|".join(str(part) for part in parts)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return f"cache:{prefix}:{digest}"


async def get_cached_payload(prefix: str, *parts: object) -> dict | list | None:
    return await cache_get_json(make_cache_key(prefix, *parts))


async def set_cached_payload(prefix: str, value: dict | list, ttl: int, *parts: object) -> None:
    await cache_set_json(make_cache_key(prefix, *parts), value, ttl)


async def invalidate_cache_prefix(prefix: str) -> None:
    cursor = 0
    pattern = f"cache:{prefix}:*"
    while True:
        cursor, keys = await redis_client.scan(cursor=cursor, match=pattern, count=200)
        if keys:
            await redis_client.delete(*keys)
        if cursor == 0:
            break


ANALYSIS_TTL = settings.ANALYSIS_CACHE_TTL_SECONDS
PREDICTIONS_TTL = settings.PREDICTION_CACHE_TTL_SECONDS
FIXTURE_TTL = settings.FIXTURE_CACHE_TTL_SECONDS
