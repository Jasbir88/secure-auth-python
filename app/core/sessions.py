"""Session revocation helpers."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import RefreshToken


def revoke_active_refresh_tokens(db: Session, user_id: UUID) -> int:
    """Revoke every active refresh token belonging to a user."""
    return (
        db.query(RefreshToken)
        .filter(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked.is_(False),
        )
        .update(
            {"revoked": True},
            synchronize_session=False,
        )
    )
