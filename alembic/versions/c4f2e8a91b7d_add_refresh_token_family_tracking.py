"""add refresh token family tracking

Revision ID: c4f2e8a91b7d
Revises: 5e3526e9e493
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.types import GUID

revision: str = "c4f2e8a91b7d"
down_revision: Union[str, Sequence[str], None] = "5e3526e9e493"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add refresh-token family and rotation lineage fields."""
    with op.batch_alter_table("refresh_tokens") as batch_op:
        batch_op.add_column(sa.Column("family_id", GUID(), nullable=True))
        batch_op.add_column(sa.Column("replaced_by_token_id", GUID(), nullable=True))

    # Existing refresh tokens each become the root of their own family.
    connection = op.get_bind()
    refresh_tokens = sa.table(
        "refresh_tokens",
        sa.column("id", GUID()),
        sa.column("family_id", GUID()),
    )
    connection.execute(refresh_tokens.update().values(family_id=refresh_tokens.c.id))

    with op.batch_alter_table("refresh_tokens") as batch_op:
        batch_op.alter_column(
            "family_id",
            existing_type=GUID(),
            nullable=False,
        )
        batch_op.create_index(
            "ix_refresh_tokens_family_id",
            ["family_id"],
            unique=False,
        )


def downgrade() -> None:
    """Remove refresh-token family tracking."""
    with op.batch_alter_table("refresh_tokens") as batch_op:
        batch_op.drop_index("ix_refresh_tokens_family_id")
        batch_op.drop_column("replaced_by_token_id")
        batch_op.drop_column("family_id")
