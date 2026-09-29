"""Tests for one-time authentication action-token lifecycle."""

from datetime import timedelta

from app.core.auth_actions import (
    EMAIL_VERIFICATION_PURPOSE,
    consume_auth_action_token,
    issue_auth_action_token,
)
from app.core.security import hash_auth_action_token
from app.db.models import AuthActionToken, User, utc_now_naive


def create_user(db_session, email: str = "actions@example.com") -> User:
    user = User(
        email=email,
        password_hash="test-password-hash",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_issued_token_is_stored_only_as_hash(db_session) -> None:
    user = create_user(db_session)

    raw_token = issue_auth_action_token(
        db_session,
        user,
        purpose=EMAIL_VERIFICATION_PURPOSE,
        expires_in=timedelta(hours=24),
    )
    db_session.commit()

    stored = db_session.query(AuthActionToken).one()

    assert stored.token_hash == hash_auth_action_token(raw_token)
    assert stored.token_hash != raw_token
    assert stored.purpose == EMAIL_VERIFICATION_PURPOSE
    assert stored.consumed_at is None


def test_new_token_invalidates_previous_unconsumed_token(db_session) -> None:
    user = create_user(db_session)

    first_raw = issue_auth_action_token(
        db_session,
        user,
        purpose=EMAIL_VERIFICATION_PURPOSE,
        expires_in=timedelta(hours=24),
    )
    db_session.commit()

    second_raw = issue_auth_action_token(
        db_session,
        user,
        purpose=EMAIL_VERIFICATION_PURPOSE,
        expires_in=timedelta(hours=24),
    )
    db_session.commit()

    first = (
        db_session.query(AuthActionToken)
        .filter(
            AuthActionToken.token_hash == hash_auth_action_token(first_raw),
        )
        .one()
    )

    second = (
        db_session.query(AuthActionToken)
        .filter(
            AuthActionToken.token_hash == hash_auth_action_token(second_raw),
        )
        .one()
    )

    assert first.consumed_at is not None
    assert second.consumed_at is None


def test_token_can_be_consumed_only_once(db_session) -> None:
    user = create_user(db_session)

    raw_token = issue_auth_action_token(
        db_session,
        user,
        purpose=EMAIL_VERIFICATION_PURPOSE,
        expires_in=timedelta(hours=24),
    )
    db_session.commit()

    consumed = consume_auth_action_token(
        db_session,
        raw_token,
        purpose=EMAIL_VERIFICATION_PURPOSE,
    )
    db_session.commit()

    assert consumed is not None

    reused = consume_auth_action_token(
        db_session,
        raw_token,
        purpose=EMAIL_VERIFICATION_PURPOSE,
    )

    assert reused is None


def test_expired_token_cannot_be_consumed(db_session) -> None:
    user = create_user(db_session)

    raw_token = issue_auth_action_token(
        db_session,
        user,
        purpose=EMAIL_VERIFICATION_PURPOSE,
        expires_in=timedelta(hours=24),
    )
    db_session.commit()

    stored = db_session.query(AuthActionToken).one()
    stored.expires_at = utc_now_naive() - timedelta(seconds=1)
    db_session.commit()

    consumed = consume_auth_action_token(
        db_session,
        raw_token,
        purpose=EMAIL_VERIFICATION_PURPOSE,
    )

    assert consumed is None


def test_wrong_purpose_cannot_consume_token(db_session) -> None:
    user = create_user(db_session)

    raw_token = issue_auth_action_token(
        db_session,
        user,
        purpose=EMAIL_VERIFICATION_PURPOSE,
        expires_in=timedelta(hours=24),
    )
    db_session.commit()

    consumed = consume_auth_action_token(
        db_session,
        raw_token,
        purpose="password_reset",
    )

    assert consumed is None
