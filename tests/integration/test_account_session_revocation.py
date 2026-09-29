"""Integration tests for account-state and credential-change revocation."""

from app.core.security import hash_refresh_token
from app.db.models import RefreshToken, User

from tests.auth_helpers import register_verified_user

PASSWORD = "SecurePass123!"
NEW_PASSWORD = "StrongerPass456!"


def register(client, email: str):
    return register_verified_user(
        client,
        email,
        PASSWORD,
    )


def headers(access_token: str):
    return {"Authorization": f"Bearer {access_token}"}


def test_weak_password_change_is_rejected_without_revoking_session(client):
    tokens = register(client, "weak-change@example.com")

    response = client.post(
        "/users/me/change-password",
        headers=headers(tokens["access_token"]),
        json={
            "current_password": PASSWORD,
            "new_password": "short",
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid password data"}

    # A rejected password change must not invalidate the current session.
    assert (
        client.get(
            "/users/me",
            headers=headers(tokens["access_token"]),
        ).status_code
        == 200
    )

    login = client.post(
        "/auth/login",
        json={
            "email": "weak-change@example.com",
            "password": PASSWORD,
        },
    )
    assert login.status_code == 200


def test_password_change_invalidates_all_existing_sessions(client, db_session):
    first = register(client, "password-change@example.com")

    second_login = client.post(
        "/auth/login",
        json={
            "email": "password-change@example.com",
            "password": PASSWORD,
        },
    )
    assert second_login.status_code == 200
    second = second_login.json()

    changed = client.post(
        "/users/me/change-password",
        headers=headers(first["access_token"]),
        json={
            "current_password": PASSWORD,
            "new_password": NEW_PASSWORD,
        },
    )
    assert changed.status_code == 200

    for access_token in (
        first["access_token"],
        second["access_token"],
    ):
        response = client.get(
            "/users/me",
            headers=headers(access_token),
        )
        assert response.status_code == 401

    for refresh_token in (
        first["refresh_token"],
        second["refresh_token"],
    ):
        response = client.post(
            "/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert response.status_code == 401

    old_login = client.post(
        "/auth/login",
        json={
            "email": "password-change@example.com",
            "password": PASSWORD,
        },
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/auth/login",
        json={
            "email": "password-change@example.com",
            "password": NEW_PASSWORD,
        },
    )
    assert new_login.status_code == 200

    user = (
        db_session.query(User).filter(User.email == "password-change@example.com").one()
    )
    active_refresh_tokens = (
        db_session.query(RefreshToken)
        .filter(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked.is_(False),
        )
        .count()
    )

    # Only the new post-password-change login should remain active.
    assert active_refresh_tokens == 1


def test_account_deactivation_invalidates_sessions_and_blocks_login(client):
    tokens = register(client, "deactivate@example.com")

    response = client.delete(
        "/users/me",
        headers=headers(tokens["access_token"]),
    )
    assert response.status_code == 200

    protected = client.get(
        "/users/me",
        headers=headers(tokens["access_token"]),
    )
    assert protected.status_code == 401

    refreshed = client.post(
        "/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refreshed.status_code == 401

    login = client.post(
        "/auth/login",
        json={
            "email": "deactivate@example.com",
            "password": PASSWORD,
        },
    )
    assert login.status_code == 403


def test_inactive_user_fails_closed_even_without_token_version_change(
    client, db_session
):
    tokens = register(client, "inactive-state@example.com")

    user = (
        db_session.query(User).filter(User.email == "inactive-state@example.com").one()
    )

    original_token_version = user.token_version
    user.is_active = False
    db_session.commit()

    assert user.token_version == original_token_version

    protected = client.get(
        "/users/me",
        headers=headers(tokens["access_token"]),
    )
    assert protected.status_code == 401
    assert protected.json()["detail"] == "Token has been revoked"

    refreshed = client.post(
        "/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refreshed.status_code == 401

    stored_refresh = (
        db_session.query(RefreshToken)
        .filter(RefreshToken.token_hash == hash_refresh_token(tokens["refresh_token"]))
        .one()
    )
    assert stored_refresh.revoked is True
