"""Helpers for tests that need a fully verified authenticated user."""

from app.main import app

DEFAULT_PASSWORD = "SecurePass123!"


def register_and_verify(
    client,
    email: str,
    password: str = DEFAULT_PASSWORD,
) -> None:
    response = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": password,
        },
    )
    assert response.status_code == 201, response.text

    token = app.state.email_sender.verification_tokens[email]

    response = client.post(
        "/auth/verify-email",
        json={"token": token},
    )
    assert response.status_code == 200, response.text


def register_verified_user(
    client,
    email: str,
    password: str = DEFAULT_PASSWORD,
) -> dict:
    register_and_verify(
        client,
        email,
        password,
    )

    response = client.post(
        "/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )
    assert response.status_code == 200, response.text

    return response.json()
