"""
Tests for token blacklist functionality.
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

from app.core.token_blacklist import TokenBlacklist


class TestTokenBlacklist:
    """Unit tests for TokenBlacklist class."""

    @pytest.fixture
    def blacklist(self):
        return TokenBlacklist()

    @pytest.mark.asyncio
    async def test_add_token_to_blacklist(self, blacklist):
        """Test adding a token JTI to blacklist."""
        jti = "test-jti-12345"
        exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())

        with patch.object(blacklist, "_get_redis") as mock_redis:
            mock_client = AsyncMock()
            mock_redis.return_value = mock_client

            await blacklist.add(jti, exp)

            mock_client.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_is_blacklisted_returns_true(self, blacklist):
        """Test checking blacklisted token returns True."""
        jti = "blacklisted-jti"

        with patch.object(blacklist, "_get_redis") as mock_redis:
            mock_client = AsyncMock()
            mock_client.exists.return_value = 1
            mock_redis.return_value = mock_client

            result = await blacklist.is_blacklisted(jti)

            assert result is True

    @pytest.mark.asyncio
    async def test_is_blacklisted_returns_false(self, blacklist):
        """Test checking non-blacklisted token returns False."""
        jti = "valid-jti"

        with patch.object(blacklist, "_get_redis") as mock_redis:
            mock_client = AsyncMock()
            mock_client.exists.return_value = 0
            mock_redis.return_value = mock_client

            result = await blacklist.is_blacklisted(jti)

            assert result is False

    @pytest.mark.asyncio
    async def test_expired_token_not_added(self, blacklist):
        """Test that expired tokens are not added to blacklist."""
        jti = "expired-jti"
        exp = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp())

        with patch.object(blacklist, "_get_redis") as mock_redis:
            mock_client = AsyncMock()
            mock_redis.return_value = mock_client

            await blacklist.add(jti, exp)

            mock_client.setex.assert_not_called()
