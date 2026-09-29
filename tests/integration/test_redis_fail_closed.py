"""Security tests for Redis-backed revocation failure behavior."""

from unittest.mock import AsyncMock, patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.redis_runtime import initialize_required_redis
from app.main import app


PASSWORD = "SecurePass123!"


class BrokenBlacklist:
    async def is_blacklisted(self, _jti: str) -> bool:
        raise RedisConnectionError("Redis unavailable")

    async def add(self, _jti: str, _exp: int) -> None:
        raise RedisConnectionError("Redis unavailable")


class WorkingBlacklist:
    def __init__(self):
        self.values = set()

    async def is_blacklisted(self, jti: str) -> bool:
        return jti in self.values

    async def add(self, jti: str, _exp: int) -> None:
        self.values.add(jti)


def register(client, email: str):
    response = client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_required_redis_startup_fails_when_ping_fails():
    redis_client = AsyncMock()
    redis_client.ping.side_effect = RedisConnectionError(
        "Redis unavailable"
    )

    with patch(
        "app.core.redis_runtime.aioredis.from_url",
        return_value=redis_client,
    ):
        with pytest.raises(RedisConnectionError):
            await initialize_required_redis()

    redis_client.aclose.assert_awaited_once()


def test_protected_route_fails_closed_without_blacklist(client):
    tokens = register(client, "missing-blacklist@example.com")
    app.state.token_blacklist = None

    response = client.get(
        "/users/me",
        headers={
            "Authorization": f"Bearer {tokens['access_token']}",
        },
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Authentication service temporarily unavailable"
    }


def test_protected_route_fails_closed_when_redis_errors(client):
    tokens = register(client, "redis-read-failure@example.com")
    app.state.token_blacklist = BrokenBlacklist()

    response = client.get(
        "/users/me",
        headers={
            "Authorization": f"Bearer {tokens['access_token']}",
        },
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Authentication service temporarily unavailable"
    }


def test_logout_reports_blacklist_write_failure_and_can_retry(client):
    tokens = register(client, "redis-write-failure@example.com")

    app.state.token_blacklist = BrokenBlacklist()

    first = client.post(
        "/auth/logout",
        headers={
            "Authorization": f"Bearer {tokens['access_token']}",
        },
        json={"refresh_token": tokens["refresh_token"]},
    )

    assert first.status_code == 503
    assert first.json() == {
        "detail": "Authentication service temporarily unavailable"
    }

    app.state.token_blacklist = WorkingBlacklist()

    retry = client.post(
        "/auth/logout",
        headers={
            "Authorization": f"Bearer {tokens['access_token']}",
        },
        json={"refresh_token": tokens["refresh_token"]},
    )

    assert retry.status_code == 200


def test_rate_limiter_redis_failure_returns_503(client):
    original_redis = app.state.redis

    broken_redis = AsyncMock()
    broken_redis.eval.side_effect = RedisConnectionError(
        "Redis unavailable"
    )

    app.state.redis = broken_redis

    try:
        response = client.post(
            "/auth/login",
            json={
                "email": "nobody@example.com",
                "password": PASSWORD,
            },
        )
    finally:
        app.state.redis = original_redis

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Service temporarily unavailable"
    }
