import orjson
from redis.asyncio import Redis
from core.config import settings

redis_client: Redis = Redis.from_url(
    settings.redis_url,
    decode_responses=True,
    encoding="utf-8",
)


async def cache_get(key: str) -> str | None:
    return await redis_client.get(key)


async def cache_set(key: str, value: str, ttl: int) -> None:
    await redis_client.set(key, value, ex=ttl)


async def cache_get_json(key: str) -> dict | list | None:
    raw = await redis_client.get(key)
    if raw is None:
        return None
    return orjson.loads(raw)


async def cache_set_json(key: str, value: dict | list, ttl: int) -> None:
    await redis_client.set(key, orjson.dumps(value).decode(), ex=ttl)


async def acquire_lock(key: str, ttl: int) -> bool:
    """
    SETNX lock pattern — returns True if lock acquired.
    Matches the war-intel-dashboard Redis lock pattern.
    """
    result = await redis_client.set(key, "1", ex=ttl, nx=True)
    return result is True


async def release_lock(key: str) -> None:
    await redis_client.delete(key)
