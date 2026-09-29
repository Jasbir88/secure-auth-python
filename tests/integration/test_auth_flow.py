"""
Integration tests for complete auth flow.
"""

from app.db.models import User


class TestAuthFlow:
    """Test complete authentication workflows."""

    def test_register_login_logout_flow(self, client, db_session):
        """Test complete user journey."""
        # Register
        response = client.post(
            "/auth/register",
            json={
                "email": "newuser@example.com",
                "password": "SecurePass123!",
            },
        )
        assert response.status_code == 201
        tokens = response.json()
        assert "access_token" in tokens
        assert "refresh_token" in tokens

        # Access protected route
        response = client.get(
            "/users/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        assert response.status_code == 200
        assert response.json()["email"] == "newuser@example.com"

        # Refresh token
        response = client.post(
            "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert response.status_code == 200
        new_tokens = response.json()
        assert new_tokens["access_token"] != tokens["access_token"]

    def test_weak_registration_rejected_and_not_stored(self, client, db_session):
        """Weak registration passwords fail before user creation."""
        email = "weak-password@example.com"
        password = "short"

        response = client.post(
            "/auth/register",
            json={
                "email": email,
                "password": password,
            },
        )

        assert response.status_code == 422
        assert response.json() == {"detail": "Invalid registration data"}
        assert password not in response.text

        stored_user = db_session.query(User).filter(User.email == email).first()
        assert stored_user is None

    def test_invalid_login(self, client, db_session):
        """Test login with wrong credentials."""
        response = client.post(
            "/auth/login",
            json={
                "email": "nonexistent@example.com",
                "password": "WrongPass123!",
            },
        )
        assert response.status_code == 401

    def test_duplicate_registration(self, client, db_session):
        """Test registering same email twice."""
        user_data = {
            "email": "duplicate@example.com",
            "password": "SecurePass123!",
        }

        # First registration
        response = client.post("/auth/register", json=user_data)
        assert response.status_code == 201

        # Second registration - should fail
        response = client.post("/auth/register", json=user_data)
        assert response.status_code == 409
