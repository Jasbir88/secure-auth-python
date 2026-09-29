from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from app.core.rate_limit import RateLimiter


def make_request(
    redis,
    *,
    headers=None,
    client=("127.0.0.1", 12345),
):
    app = SimpleNamespace(
        state=SimpleNamespace(redis=redis)
    )

    encoded_headers = [
        (
            name.lower().encode("latin-1"),
            value.encode("latin-1"),
        )
        for name, value in (headers or {}).items()
    ]

    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/auth/login",
            "raw_path": b"/auth/login",
            "query_string": b"",
            "headers": encoded_headers,
            "client": client,
            "server": ("testserver", 80),
            "app": app,
        }
    )


@pytest.mark.asyncio
async def test_rate_limiter_allows_request():
    redis = AsyncMock()
    redis.eval.return_value = 0

    limiter = RateLimiter(
        times=5,
        seconds=60,
    )

    await limiter(
        make_request(redis),
        Response(),
    )

    redis.eval.assert_awaited_once()


@pytest.mark.asyncio
async def test_rate_limiter_returns_429_with_retry_after():
    redis = AsyncMock()
    redis.eval.return_value = 1500

    limiter = RateLimiter(
        times=5,
        seconds=60,
    )

    with pytest.raises(HTTPException) as exc:
        await limiter(
            make_request(redis),
            Response(),
        )

    assert exc.value.status_code == 429
    assert exc.value.detail == "Too Many Requests"
    assert exc.value.headers == {
        "Retry-After": "2"
    }


@pytest.mark.asyncio
async def test_rate_limiter_fails_closed_without_redis():
    limiter = RateLimiter(
        times=5,
        seconds=60,
    )

    request = make_request(None)

    with pytest.raises(HTTPException) as exc:
        await limiter(
            request,
            Response(),
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == (
        "Service temporarily unavailable"
    )


@pytest.mark.asyncio
async def test_rate_limiter_uses_forwarded_client_identity():
    redis = AsyncMock()
    redis.eval.return_value = 0

    limiter = RateLimiter(
        times=5,
        seconds=60,
    )

    request = make_request(
        redis,
        headers={
            "X-Forwarded-For": "100.68.41.76, 127.0.0.1",
        },
    )

    await limiter(
        request,
        Response(),
    )

    args = redis.eval.await_args.args
    key = args[2]

    assert "100.68.41.76:/auth/login:" in key
    assert "127.0.0.1:/auth/login:" not in key
