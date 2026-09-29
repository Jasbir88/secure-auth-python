"""add email verification state and auth action tokens

Revision ID: d6f8a1c2b3e4
Revises: 8a7d3f91c2e6
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.types import GUID

revision: str = "d6f8a1c2b3e4"
down_revision: Union[str, Sequence[str], None] = "8a7d3f91c2e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "email_verified_at",
            sa.DateTime(),
            nullable=True,
        ),
    )

    # Preserve existing account behavior. Existing users are treated as
    # verified when email-verification enforcement is introduced later.
    op.execute("""
        UPDATE users
        SET email_verified_at = created_at
        WHERE email_verified_at IS NULL
        """)

    op.create_table(
        "auth_action_tokens",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("user_id", GUID(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_auth_action_tokens_user_id",
        "auth_action_tokens",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_auth_action_tokens_purpose",
        "auth_action_tokens",
        ["purpose"],
        unique=False,
    )
    op.create_index(
        "ix_auth_action_tokens_token_hash",
        "auth_action_tokens",
        ["token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_auth_action_tokens_token_hash",
        table_name="auth_action_tokens",
    )
    op.drop_index(
        "ix_auth_action_tokens_purpose",
        table_name="auth_action_tokens",
    )
    op.drop_index(
        "ix_auth_action_tokens_user_id",
        table_name="auth_action_tokens",
    )
    op.drop_table("auth_action_tokens")
    op.drop_column("users", "email_verified_at")
