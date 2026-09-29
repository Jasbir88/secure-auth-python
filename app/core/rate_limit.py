"""Redis-backed request rate limiting.

The limiter intentionally fails closed when Redis is unavailable.
"""

from __future__ import annotations

import math

from fastapi import HTTPException, Request, Response, status


RATE_LIMIT_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])

local current = tonumber(redis.call("GET", key) or "0")

if current == 0 then
    redis.call("SET", key, 1, "PX", ttl)
    return 0
end

if current >= limit then
    return redis.call("PTTL", key)
end

redis.call("INCR", key)
return 0
"""


class RateLimiter:
    """FastAPI dependency backed by the application's required Redis."""

    def __init__(self, *, times: int, seconds: int):
        if times <= 0 or seconds <= 0:
            raise ValueError(
                "times and seconds must be positive"
            )

        self.times = times
        self.seconds = seconds

    async def __call__(
        self,
        request: Request,
        response: Response,
    ) -> None:
        redis = getattr(
            request.app.state,
            "redis",
            None,
        )

        if redis is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Service temporarily unavailable",
            )

        forwarded = request.headers.get("X-Forwarded-For")

        if forwarded:
            client = forwarded.split(",", 1)[0].strip()
        elif request.client is not None:
            client = request.client.host
        else:
            client = "unknown"

        path = request.scope.get(
            "path",
            request.url.path,
        )

        key = (
            "secure-auth:rate-limit:"
            f"{client}:{path}:"
            f"{self.times}:{self.seconds}"
        )

        remaining_ms = await redis.eval(
            RATE_LIMIT_SCRIPT,
            1,
            key,
            self.times,
            self.seconds * 1000,
        )

        remaining_ms = int(remaining_ms)

        if remaining_ms > 0:
            retry_after = max(
                1,
                math.ceil(
                    remaining_ms / 1000
                ),
            )

            response.headers[
                "Retry-After"
            ] = str(retry_after)

            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too Many Requests",
                headers={
                    "Retry-After": str(
                        retry_after
                    )
                },
            )
