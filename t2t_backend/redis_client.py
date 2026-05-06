"""
redis_client.py — Shared async Redis connection.
Falls back to in-memory fakeredis if a real Redis server is unavailable.
"""
import logging
import redis.asyncio as aioredis

from config import settings

logger = logging.getLogger(__name__)
_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        try:
            real = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2,
            )
            await real.ping()
            _redis = real
            logger.info("Connected to real Redis at %s", settings.REDIS_URL)
        except Exception as e:
            logger.warning("Real Redis unavailable (%s) — falling back to in-memory fakeredis", e)
            import fakeredis.aioredis as fake_aio
            _redis = fake_aio.FakeRedis(decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis:
        try:
            await _redis.aclose()
        except Exception:
            pass
        _redis = None
