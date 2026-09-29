"""Integration tests for refresh-token rotation and reuse detection."""

from app.core.security import hash_refresh_token
from app.db.models import RefreshToken
from tests.auth_helpers import register_verified_user


def register(client, email: str):
    return register_verified_user(
        client,
        email,
        "SecurePass123!",
    )


def test_refresh_rotation_preserves_family_and_records_replacement(client, db_session):
    tokens = register(client, "rotation@example.com")
    original_value = tokens["refresh_token"]

    response = client.post(
        "/auth/refresh",
        json={"refresh_token": original_value},
    )
    assert response.status_code == 200
    replacement_value = response.json()["refresh_token"]

    original = (
        db_session.query(RefreshToken)
        .filter(RefreshToken.token_hash == hash_refresh_token(original_value))
        .one()
    )
    replacement = (
        db_session.query(RefreshToken)
        .filter(RefreshToken.token_hash == hash_refresh_token(replacement_value))
        .one()
    )

    assert original.revoked is True
    assert replacement.revoked is False
    assert original.family_id == replacement.family_id
    assert original.replaced_by_token_id == replacement.id


def test_reusing_rotated_token_revokes_its_family(client, db_session):
    tokens = register(client, "replay@example.com")
    original_value = tokens["refresh_token"]

    rotation = client.post(
        "/auth/refresh",
        json={"refresh_token": original_value},
    )
    assert rotation.status_code == 200
    replacement_value = rotation.json()["refresh_token"]

    replay = client.post(
        "/auth/refresh",
        json={"refresh_token": original_value},
    )
    assert replay.status_code == 401
    assert replay.json() == {"detail": "Invalid or expired refresh token"}

    descendant = client.post(
        "/auth/refresh",
        json={"refresh_token": replacement_value},
    )
    assert descendant.status_code == 401

    original = (
        db_session.query(RefreshToken)
        .filter(RefreshToken.token_hash == hash_refresh_token(original_value))
        .one()
    )

    family = (
        db_session.query(RefreshToken)
        .filter(RefreshToken.family_id == original.family_id)
        .all()
    )

    assert len(family) == 2
    assert all(token.revoked for token in family)


def test_reuse_does_not_revoke_an_unrelated_session_family(client, db_session):
    first_session = register(client, "separate-family@example.com")

    second_login = client.post(
        "/auth/login",
        json={
            "email": "separate-family@example.com",
            "password": "SecurePass123!",
        },
    )
    assert second_login.status_code == 200
    second_session = second_login.json()

    first_original = first_session["refresh_token"]

    rotation = client.post(
        "/auth/refresh",
        json={"refresh_token": first_original},
    )
    assert rotation.status_code == 200

    replay = client.post(
        "/auth/refresh",
        json={"refresh_token": first_original},
    )
    assert replay.status_code == 401

    unaffected = client.post(
        "/auth/refresh",
        json={"refresh_token": second_session["refresh_token"]},
    )
    assert unaffected.status_code == 200
