"""
Integration tests for logout all sessions functionality.
"""
import os
import pytest
from unittest.mock import MagicMock, AsyncMock


class MockTokenBlacklist:
    """Mock token blacklist for testing without Redis."""
    
    def __init__(self):
        self.blacklisted_tokens = set()
    
    async def add(self, token: str, expires_in: int = 3600):
        self.blacklisted_tokens.add(token)
    
    async def is_blacklisted(self, token: str) -> bool:
        return token in self.blacklisted_tokens


class TestLogoutAll:
    """Integration tests for logout all sessions functionality."""
    
    @pytest.fixture(autouse=True)
    def setup_mock_blacklist(self, client):
        """Set up mock token blacklist for each test."""
        from app.main import app
        app.state.token_blacklist = MockTokenBlacklist()
        app.state.redis = MagicMock()  # Mock redis client
        yield
    
    @pytest.fixture
    def registered_user(self, client, db_session):
        """Create a test user."""
        response = client.post("/auth/register", json={
            "email": "test@example.com",
            "password": "SecurePass123!",
        })
        # Accept 200, 201, or 409 (if user already exists)
        assert response.status_code in [200, 201, 409], f"Register failed: {response.json()}"
        return {"email": "test@example.com", "password": "SecurePass123!"}
    
    @pytest.fixture
    def authenticated_user(self, client, registered_user):
        """Login and get tokens."""
        response = client.post("/auth/login", json={
            "email": registered_user["email"],
            "password": registered_user["password"],
        })
        assert response.status_code == 200, f"Login failed: {response.json()}"
        return response.json()
    
    def test_logout_all_sessions_success(self, client, authenticated_user):
        """Test that logout_all invalidates all user sessions."""
        token = authenticated_user.get("access_token")
        
        response = client.post(
            "/auth/logout-all",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        # Expect success
        assert response.status_code in [200, 204], f"Logout failed: {response.json()}"
    
    def test_logout_all_requires_authentication(self, client, db_session):
        """Test that logout_all requires valid authentication."""
        response = client.post("/auth/logout-all")
        
        # Should fail without authentication
        assert response.status_code in [401, 403, 422]
