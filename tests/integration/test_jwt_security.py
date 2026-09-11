"""Verify the JWT policy is enforced by the actual protected and logout routes."""

import jwt
import pytest

from app.core.config import settings
from app.core.security import decode_access_token


@pytest.fixture
def registered_tokens(client):
    response = client.post(
        "/auth/register",
        json={"email": "claims@example.com", "password": "SecurePass123!"},
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("iss", "another-issuer"),
        ("aud", "another-api"),
        ("iss", None),
        ("aud", None),
        ("token_version", None),
    ],
)
def test_users_me_rejects_foreign_or_incomplete_tokens(
    client, registered_tokens, claim, value
):
    payload = decode_access_token(registered_tokens["access_token"])
    if value is None:
        payload.pop(claim)
    else:
        payload[claim] = value
    token = jwt.encode(
        payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    response = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_logout_revokes_access_and_refresh_tokens_with_new_claims(
    client, registered_tokens
):
    headers = {"Authorization": f"Bearer {registered_tokens['access_token']}"}
    refresh_request = {"refresh_token": registered_tokens["refresh_token"]}
    assert client.get("/users/me", headers=headers).status_code == 200

    response = client.post("/auth/logout", headers=headers, json=refresh_request)
    assert response.status_code == 200

    response = client.get("/users/me", headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "Token has been revoked"
    assert client.post("/auth/refresh", json=refresh_request).status_code == 401
