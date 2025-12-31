"""
Database models.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Boolean, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import GUID


def utc_now_naive() -> datetime:
    """Return current UTC time as naive datetime for DB compatibility."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    """User model."""
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive
    )
    token_version: Mapped[int] = mapped_column(Integer, default=1)

    # Relationship to refresh tokens
    refresh_tokens = relationship("RefreshToken", back_populates="user")


class RefreshToken(Base):
    """Refresh token model for JWT refresh flow."""
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE")
    )
    token_hash: Mapped[str] = mapped_column(String, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive
    )

    # Relationship back to user
    user = relationship("User", back_populates="refresh_tokens")
