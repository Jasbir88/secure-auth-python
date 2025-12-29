"""
Token blacklist service using Redis.
"""
from datetime import datetime
import redis.asyncio as aioredis


class TokenBlacklist:
    """Redis-based token blacklist for JWT revocation."""
    
    def __init__(self, redis_client: aioredis.Redis):
        self.redis = redis_client
        self.prefix = "blacklist:"
    
    async def add(self, token_jti: str, expires_at: datetime) -> None:
        """Add a token to the blacklist."""
        key = f"{self.prefix}{token_jti}"
        ttl = int((expires_at - datetime.utcnow()).total_seconds())
        
        if ttl > 0:
            await self.redis.setex(key, ttl, "revoked")
    
    async def is_blacklisted(self, token_jti: str) -> bool:
        """Check if a token is blacklisted."""
        key = f"{self.prefix}{token_jti}"
        return await self.redis.exists(key) > 0
