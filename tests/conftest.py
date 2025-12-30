"""
Pytest configuration and fixtures.
"""
import pytest


@pytest.fixture
def test_user_credentials() -> dict:
    """Test user login credentials."""
    return {
        "email": "test@example.com",
        "password": "testpassword123"
    }
