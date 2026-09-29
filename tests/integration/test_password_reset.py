"""Integration tests for password-reset account recovery."""

from datetime import timedelta

from app.core.email_delivery import EmailDeliveryError
from app.core.security import hash_auth_action_token
from app.db.models import AuthActionToken, utc_now_naive
from app.main import app
from tests.auth_helpers import register_and_verify, register_verified_user

OLD_PASSWORD = "SecurePass123!"
NEW_PASSWORD = "ReplacementPass456!"

GENERIC_FORGOT_RESPONSE = {
    "message": (
        "If an eligible account exists, " "a password reset email has been sent."
    )
}


def forgot(client, email: str):
    return client.post(
        "/auth/forgot-password",
        json={"email": email},
    )


def reset_token(email: str) -> str:
    return app.state.email_sender.password_reset_tokens[email]


def reset_password(client, token: str, password: str = NEW_PASSWORD):
    return client.post(
        "/auth/reset-password",
        json={
            "token": token,
            "new_password": password,
        },
    )


def test_forgot_password_does_not_reveal_missing_account(client):
    response = forgot(
        client,
        "missing-reset@example.com",
    )

    assert response.status_code == 200
    assert response.json() == GENERIC_FORGOT_RESPONSE
    assert (
        "missing-reset@example.com" not in app.state.email_sender.password_reset_tokens
    )


def test_unverified_account_is_not_eligible_for_password_reset(client):
    email = "unverified-reset@example.com"

    response = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": OLD_PASSWORD,
        },
    )
    assert response.status_code == 201

    response = forgot(client, email)

    assert response.status_code == 200
    assert response.json() == GENERIC_FORGOT_RESPONSE
    assert email not in app.state.email_sender.password_reset_tokens


def test_new_reset_request_invalidates_previous_token_and_token_is_one_time(
    client,
):
    email = "replace-reset@example.com"
    register_and_verify(client, email, OLD_PASSWORD)

    assert forgot(client, email).status_code == 200
    first = reset_token(email)

    assert forgot(client, email).status_code == 200
    second = reset_token(email)

    assert first != second

    old = reset_password(client, first)
    assert old.status_code == 400
    assert old.json() == {"detail": "Invalid or expired password reset token"}

    current = reset_password(client, second)
    assert current.status_code == 200
    assert current.json() == {"message": "Password reset successfully"}

    replay = reset_password(client, second)
    assert replay.status_code == 400

    old_login = client.post(
        "/auth/login",
        json={
            "email": email,
            "password": OLD_PASSWORD,
        },
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/auth/login",
        json={
            "email": email,
            "password": NEW_PASSWORD,
        },
    )
    assert new_login.status_code == 200


def test_invalid_new_password_does_not_consume_reset_token(client):
    email = "policy-reset@example.com"
    register_and_verify(client, email, OLD_PASSWORD)

    assert forgot(client, email).status_code == 200
    token = reset_token(email)

    rejected = reset_password(
        client,
        token,
        "weak",
    )

    assert rejected.status_code == 422
    assert rejected.json() == {"detail": "Invalid password data"}

    accepted = reset_password(
        client,
        token,
        NEW_PASSWORD,
    )

    assert accepted.status_code == 200


def test_successful_reset_invalidates_existing_sessions(client):
    email = "sessions-reset@example.com"

    tokens = register_verified_user(
        client,
        email,
        OLD_PASSWORD,
    )

    headers = {
        "Authorization": f"Bearer {tokens['access_token']}",
    }

    assert forgot(client, email).status_code == 200
    token = reset_token(email)

    reset = reset_password(client, token)
    assert reset.status_code == 200

    old_access = client.get(
        "/users/me",
        headers=headers,
    )
    assert old_access.status_code == 401

    old_refresh = client.post(
        "/auth/refresh",
        json={
            "refresh_token": tokens["refresh_token"],
        },
    )
    assert old_refresh.status_code == 401


def test_authenticated_password_change_invalidates_pending_reset(client):
    email = "change-password-reset@example.com"

    tokens = register_verified_user(
        client,
        email,
        OLD_PASSWORD,
    )

    assert forgot(client, email).status_code == 200
    token = reset_token(email)

    changed = client.post(
        "/users/me/change-password",
        headers={
            "Authorization": f"Bearer {tokens['access_token']}",
        },
        json={
            "current_password": OLD_PASSWORD,
            "new_password": NEW_PASSWORD,
        },
    )

    assert changed.status_code == 200

    stale_reset = reset_password(
        client,
        token,
        "AnotherSecure789!",
    )
    assert stale_reset.status_code == 400


def test_email_change_invalidates_pending_reset(client):
    old_email = "reset-old-email@example.com"
    new_email = "reset-new-email@example.com"

    tokens = register_verified_user(
        client,
        old_email,
        OLD_PASSWORD,
    )

    assert forgot(client, old_email).status_code == 200
    token = reset_token(old_email)

    changed = client.patch(
        "/users/me",
        headers={
            "Authorization": f"Bearer {tokens['access_token']}",
        },
        json={"email": new_email},
    )

    assert changed.status_code == 200

    stale_reset = reset_password(
        client,
        token,
    )
    assert stale_reset.status_code == 400


def test_password_reset_delivery_failure_is_enumeration_safe_and_recoverable(
    client,
):
    email = "reset-delivery@example.com"
    register_and_verify(client, email, OLD_PASSWORD)

    original_sender = app.state.email_sender

    class BrokenResetSender:
        def __init__(self):
            self.failed_token = None

        def send_password_reset(
            self,
            *,
            recipient: str,
            token: str,
            expires_minutes: int,
        ) -> None:
            self.failed_token = token
            raise EmailDeliveryError("test reset delivery failure")

    broken = BrokenResetSender()
    app.state.email_sender = broken

    try:
        failed = forgot(client, email)
    finally:
        app.state.email_sender = original_sender

    assert failed.status_code == 200
    assert failed.json() == GENERIC_FORGOT_RESPONSE
    assert broken.failed_token

    # A retry issues a new token and invalidates the undelivered one.
    retry = forgot(client, email)

    assert retry.status_code == 200
    assert retry.json() == GENERIC_FORGOT_RESPONSE

    current_token = reset_token(email)

    assert current_token != broken.failed_token

    stale = reset_password(
        client,
        broken.failed_token,
    )
    assert stale.status_code == 400

    recovered = reset_password(
        client,
        current_token,
    )
    assert recovered.status_code == 200


def test_expired_reset_token_is_rejected(
    client,
    db_session,
):
    email = "expired-reset@example.com"
    register_and_verify(
        client,
        email,
        OLD_PASSWORD,
    )

    assert forgot(client, email).status_code == 200
    token = reset_token(email)

    stored = (
        db_session.query(AuthActionToken)
        .filter(
            AuthActionToken.token_hash == hash_auth_action_token(token),
        )
        .one()
    )

    stored.expires_at = utc_now_naive() - timedelta(seconds=1)
    db_session.commit()

    response = reset_password(
        client,
        token,
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid or expired password reset token"}


def test_email_verification_invalidates_stale_password_reset_token(
    client,
    db_session,
):
    from datetime import timedelta

    from app.core.auth_actions import (
        PASSWORD_RESET_PURPOSE,
        issue_auth_action_token,
    )
    from app.db.models import User

    email = "identity-transition-reset@example.com"

    registered = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": OLD_PASSWORD,
        },
    )
    assert registered.status_code == 201

    verification_token = app.state.email_sender.verification_tokens[email]

    user = db_session.query(User).filter(User.email == email).one()

    # Simulate a reset token created during a raced/stale identity state.
    stale_reset_token = issue_auth_action_token(
        db_session,
        user,
        purpose=PASSWORD_RESET_PURPOSE,
        expires_in=timedelta(minutes=30),
    )
    db_session.commit()

    verified = client.post(
        "/auth/verify-email",
        json={"token": verification_token},
    )

    assert verified.status_code == 200

    stale = client.post(
        "/auth/reset-password",
        json={
            "token": stale_reset_token,
            "new_password": NEW_PASSWORD,
        },
    )

    assert stale.status_code == 400
    assert stale.json() == {"detail": "Invalid or expired password reset token"}
