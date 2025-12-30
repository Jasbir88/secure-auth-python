"""
Token blacklist service using Redis.
"""
import redis.asyncio as aioredis
from datetime import datetime, timezone
from typing import Optional

from app.core.config import settings


class TokenBlacklist:
    """Redis-based token blacklist for JWT revocation."""

    def __init__(self, redis_client: Optional[aioredis.Redis] = None):
        self._redis = redis_client
        self.prefix = "token_blacklist:"

    async def _get_redis(self) -> aioredis.Redis:
        """Get or create Redis connection."""
        if self._redis is None:
            self._redis = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True
            )
        return self._redis

    async def add(self, jti: str, exp: int) -> None:
        """Add token JTI to blacklist with TTL."""
        r = await self._get_redis()
        now = int(datetime.now(timezone.utc).timestamp())
        ttl = exp - now

        if ttl > 0:
            await r.setex(
                name=f"{self.prefix}{jti}",
                time=ttl,
                value="1"
            )

    async def is_blacklisted(self, jti: str) -> bool:
        """Check if token JTI is blacklisted."""
        r = await self._get_redis()
        result = await r.exists(f"{self.prefix}{jti}")
        return result > 0

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None


# Singleton instance (used when importing directly)
token_blacklist = TokenBlacklist()
