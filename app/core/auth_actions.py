"""One-time authentication action-token lifecycle."""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.security import (
    create_auth_action_token,
    hash_auth_action_token,
)
from app.db.models import AuthActionToken, User, utc_now_naive

EMAIL_VERIFICATION_PURPOSE = "email_verification"
PASSWORD_RESET_PURPOSE = "password_reset"


def invalidate_auth_action_tokens(
    db: Session,
    user: User,
    *,
    purpose: str,
) -> int:
    """Invalidate every outstanding token for one user and purpose."""
    if not purpose or len(purpose) > 32:
        raise ValueError("Invalid auth action purpose")

    (db.query(User).filter(User.id == user.id).with_for_update().one())

    now = utc_now_naive()

    count = (
        db.query(AuthActionToken)
        .filter(
            AuthActionToken.user_id == user.id,
            AuthActionToken.purpose == purpose,
            AuthActionToken.consumed_at.is_(None),
        )
        .update(
            {"consumed_at": now},
            synchronize_session=False,
        )
    )

    db.flush()
    return count


def issue_auth_action_token(
    db: Session,
    user: User,
    *,
    purpose: str,
    expires_in: timedelta,
) -> str:
    """Issue one raw token while storing only its hash.

    Any previous unconsumed token for the same user and purpose is invalidated.
    The caller owns the transaction and must commit.
    """
    if expires_in.total_seconds() <= 0:
        raise ValueError("Auth action token expiry must be positive")

    invalidate_auth_action_tokens(
        db,
        user,
        purpose=purpose,
    )

    now = utc_now_naive()
    raw_token = create_auth_action_token()

    db.add(
        AuthActionToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=hash_auth_action_token(raw_token),
            expires_at=now + expires_in,
        )
    )

    db.flush()

    return raw_token


def consume_auth_action_token(
    db: Session,
    raw_token: str,
    *,
    purpose: str,
) -> AuthActionToken | None:
    """Consume a valid one-time token.

    Invalid, expired, wrong-purpose, and previously consumed tokens all
    produce the same result. The caller owns the transaction and must commit.
    """
    if not raw_token:
        return None

    token_hash = hash_auth_action_token(raw_token)

    # Discover the owning user without taking a token-row lock first.
    # Issuance locks User -> AuthActionToken, so consumption follows the
    # same order to avoid resend/verification deadlocks on PostgreSQL.
    user_id = (
        db.query(AuthActionToken.user_id)
        .filter(
            AuthActionToken.token_hash == token_hash,
            AuthActionToken.purpose == purpose,
        )
        .scalar()
    )

    if user_id is None:
        return None

    user = db.query(User).filter(User.id == user_id).with_for_update().first()

    if user is None:
        return None

    token = (
        db.query(AuthActionToken)
        .filter(
            AuthActionToken.token_hash == token_hash,
            AuthActionToken.purpose == purpose,
        )
        .with_for_update()
        .first()
    )

    if token is None or token.consumed_at is not None:
        return None

    now = utc_now_naive()

    if token.expires_at <= now:
        return None

    token.consumed_at = now
    db.flush()

    return token
