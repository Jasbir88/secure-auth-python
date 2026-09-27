"""Database invariants for refresh-token storage."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import RefreshToken, User


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def test_refresh_token_hash_must_be_unique(db_session):
    """The database must reject duplicate refresh-token hashes."""
    user = User(
        email="unique-refresh-hash@example.com",
        password_hash="test-password-hash",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    now = utc_now_naive()
    duplicate_hash = "same-refresh-token-hash"

    first = RefreshToken(
        user_id=user.id,
        token_hash=duplicate_hash,
        expires_at=now + timedelta(days=1),
    )
    db_session.add(first)
    db_session.commit()

    second = RefreshToken(
        user_id=user.id,
        token_hash=duplicate_hash,
        expires_at=now + timedelta(days=1),
    )
    db_session.add(second)

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()
