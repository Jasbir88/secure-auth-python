"""Required Redis startup for security-critical runtime services."""

import redis.asyncio as aioredis
from fastapi_limiter import FastAPILimiter

from app.core.config import settings
from app.core.token_blacklist import TokenBlacklist


async def initialize_required_redis():
    """Connect to Redis or fail application startup."""
    redis_client = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )

    try:
        await redis_client.ping()
        await FastAPILimiter.init(redis_client)
    except Exception:
        await redis_client.aclose()
        raise

    return redis_client, TokenBlacklist(redis_client)
