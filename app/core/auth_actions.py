"""One-time authentication action-token lifecycle."""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.security import (
    create_auth_action_token,
    hash_auth_action_token,
)
from app.db.models import AuthActionToken, User, utc_now_naive

EMAIL_VERIFICATION_PURPOSE = "email_verification"


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
    if not purpose or len(purpose) > 32:
        raise ValueError("Invalid auth action purpose")

    if expires_in.total_seconds() <= 0:
        raise ValueError("Auth action token expiry must be positive")

    # Serialize issuance for this user. Without this lock, concurrent
    # resend requests could each create a valid replacement token.
    (db.query(User).filter(User.id == user.id).with_for_update().one())

    now = utc_now_naive()

    db.query(AuthActionToken).filter(
        AuthActionToken.user_id == user.id,
        AuthActionToken.purpose == purpose,
        AuthActionToken.consumed_at.is_(None),
    ).update(
        {"consumed_at": now},
        synchronize_session=False,
    )

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
