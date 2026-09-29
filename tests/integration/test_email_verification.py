"""Integration tests for email-verification authentication flow."""

from app.core.email_delivery import EmailDeliveryError
from app.db.models import AuthActionToken, User
from app.main import app

PASSWORD = "SecurePass123!"

GENERIC_RESEND_RESPONSE = {
    "message": ("If an eligible account exists, " "a verification email has been sent.")
}


def register(client, email: str):
    return client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
        },
    )


def verification_token(email: str) -> str:
    return app.state.email_sender.verification_tokens[email]


def test_registration_creates_unverified_user_without_session_tokens(
    client,
    db_session,
):
    email = "verify-register@example.com"

    response = register(client, email)

    assert response.status_code == 201
    body = response.json()

    assert body == {
        "message": (
            "Registration successful. " "Check your email to verify your account."
        )
    }
    assert "access_token" not in body
    assert "refresh_token" not in body

    user = db_session.query(User).filter(User.email == email).one()

    assert user.email_verified_at is None

    raw_token = verification_token(email)
    assert raw_token

    stored = (
        db_session.query(AuthActionToken)
        .filter(AuthActionToken.user_id == user.id)
        .one()
    )

    assert stored.token_hash != raw_token
    assert stored.consumed_at is None


def test_login_is_blocked_until_email_is_verified(
    client,
):
    email = "verify-login@example.com"

    assert register(client, email).status_code == 201

    before = client.post(
        "/auth/login",
        json={
            "email": email,
            "password": PASSWORD,
        },
    )

    assert before.status_code == 403
    assert before.json() == {"detail": "Email verification required"}

    token = verification_token(email)

    verified = client.post(
        "/auth/verify-email",
        json={"token": token},
    )

    assert verified.status_code == 200
    assert verified.json() == {"message": "Email verified successfully"}

    after = client.post(
        "/auth/login",
        json={
            "email": email,
            "password": PASSWORD,
        },
    )

    assert after.status_code == 200
    assert after.json()["access_token"]
    assert after.json()["refresh_token"]


def test_verification_token_is_one_time(
    client,
    db_session,
):
    email = "verify-once@example.com"

    assert register(client, email).status_code == 201
    token = verification_token(email)

    first = client.post(
        "/auth/verify-email",
        json={"token": token},
    )

    assert first.status_code == 200

    db_session.expire_all()
    user = db_session.query(User).filter(User.email == email).one()
    assert user.email_verified_at is not None

    second = client.post(
        "/auth/verify-email",
        json={"token": token},
    )

    assert second.status_code == 400
    assert second.json() == {"detail": "Invalid or expired verification token"}


def test_resend_replaces_previous_token(
    client,
):
    email = "verify-resend@example.com"

    assert register(client, email).status_code == 201
    first_token = verification_token(email)

    resend = client.post(
        "/auth/resend-verification",
        json={"email": email},
    )

    assert resend.status_code == 200
    assert resend.json() == GENERIC_RESEND_RESPONSE

    second_token = verification_token(email)

    assert second_token != first_token

    old = client.post(
        "/auth/verify-email",
        json={"token": first_token},
    )

    assert old.status_code == 400

    current = client.post(
        "/auth/verify-email",
        json={"token": second_token},
    )

    assert current.status_code == 200


def test_resend_does_not_reveal_missing_account(
    client,
):
    response = client.post(
        "/auth/resend-verification",
        json={"email": "missing@example.com"},
    )

    assert response.status_code == 200
    assert response.json() == GENERIC_RESEND_RESPONSE


def test_registration_delivery_failure_is_recoverable(
    client,
    db_session,
):
    email = "delivery-recovery@example.com"
    original_sender = app.state.email_sender

    class BrokenEmailSender:
        def send_verification(
            self,
            *,
            recipient: str,
            token: str,
            expires_hours: int,
        ) -> None:
            raise EmailDeliveryError("test delivery failure")

    app.state.email_sender = BrokenEmailSender()

    try:
        response = register(client, email)
    finally:
        app.state.email_sender = original_sender

    assert response.status_code == 503
    assert response.json() == {"detail": "Verification email could not be delivered"}

    user = db_session.query(User).filter(User.email == email).one()
    assert user.email_verified_at is None

    resend = client.post(
        "/auth/resend-verification",
        json={"email": email},
    )

    assert resend.status_code == 200
    assert resend.json() == GENERIC_RESEND_RESPONSE

    token = verification_token(email)

    verified = client.post(
        "/auth/verify-email",
        json={"token": token},
    )

    assert verified.status_code == 200


def test_email_change_requires_new_verification_and_revokes_sessions(
    client,
    db_session,
):
    from tests.auth_helpers import register_verified_user

    old_email = "old-address@example.com"
    new_email = "new-address@example.com"

    tokens = register_verified_user(
        client,
        old_email,
        PASSWORD,
    )

    headers = {
        "Authorization": f"Bearer {tokens['access_token']}",
    }

    changed = client.patch(
        "/users/me",
        headers=headers,
        json={"email": new_email},
    )

    assert changed.status_code == 200
    assert changed.json()["email"] == new_email

    # The session that authorized the identity change is immediately stale.
    assert (
        client.get(
            "/users/me",
            headers=headers,
        ).status_code
        == 401
    )

    assert (
        client.post(
            "/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        ).status_code
        == 401
    )

    # Correct credentials are still insufficient until the new address
    # has been proven.
    before_verification = client.post(
        "/auth/login",
        json={
            "email": new_email,
            "password": PASSWORD,
        },
    )

    assert before_verification.status_code == 403
    assert before_verification.json() == {"detail": "Email verification required"}

    token = verification_token(new_email)

    verified = client.post(
        "/auth/verify-email",
        json={"token": token},
    )

    assert verified.status_code == 200

    after_verification = client.post(
        "/auth/login",
        json={
            "email": new_email,
            "password": PASSWORD,
        },
    )

    assert after_verification.status_code == 200

    db_session.expire_all()
    user = db_session.query(User).filter(User.email == new_email).one()
    assert user.email_verified_at is not None
