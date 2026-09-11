"""Check the costly verification work without unreliable wall-clock assertions."""

from unittest.mock import patch

import pytest

from app.api.routes import auth as auth_routes
from app.db.models import User


@pytest.mark.parametrize(
    ("email", "password", "expected_status"),
    [
        ("missing@example.com", "WrongPass123!", 401),
        ("known@example.com", "WrongPass123!", 401),
        ("known@example.com", "SecurePass123!", 200),
    ],
)
def test_login_performs_one_password_verification(
    client, db_session, email, password, expected_status
):
    response = client.post(
        "/auth/register",
        json={"email": "known@example.com", "password": "SecurePass123!"},
    )
    assert response.status_code == 201
    user = db_session.query(User).filter(User.email == "known@example.com").one()
    expected_hash = (
        user.password_hash if email == user.email else auth_routes.DUMMY_PASSWORD_HASH
    )
    with (
        patch.object(
            auth_routes, "verify_user_password", wraps=auth_routes.verify_user_password
        ) as verify,
        patch.object(
            auth_routes,
            "hash_user_password",
            side_effect=AssertionError("Do not generate password hashes during login"),
        ),
    ):
        response = client.post(
            "/auth/login", json={"email": email, "password": password}
        )
    assert response.status_code == expected_status
    verify.assert_called_once_with(password, expected_hash)
    if expected_status == 401:
        assert response.json() == {"detail": "Invalid email or password"}


def test_missing_user_is_rejected_even_if_dummy_verification_matches(client):
    with patch.object(auth_routes, "verify_user_password", return_value=True) as verify:
        response = client.post(
            "/auth/login",
            json={"email": "missing@example.com", "password": "SecurePass123!"},
        )
    verify.assert_called_once()
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password"}
