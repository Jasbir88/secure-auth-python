"""make refresh token hash unique

Revision ID: 8a7d3f91c2e6
Revises: c4f2e8a91b7d
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "8a7d3f91c2e6"
down_revision: Union[str, Sequence[str], None] = "c4f2e8a91b7d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Reject duplicates, then enforce unique refresh-token hashes."""
    connection = op.get_bind()

    duplicate_exists = connection.execute(sa.text("""
            SELECT 1
            FROM refresh_tokens
            GROUP BY token_hash
            HAVING COUNT(*) > 1
            LIMIT 1
            """)).scalar()

    if duplicate_exists is not None:
        raise RuntimeError(
            "Cannot enforce unique refresh token hashes: " "duplicate hashes exist."
        )

    op.drop_index(
        "ix_refresh_tokens_token_hash",
        table_name="refresh_tokens",
    )
    op.create_index(
        "ix_refresh_tokens_token_hash",
        "refresh_tokens",
        ["token_hash"],
        unique=True,
    )


def downgrade() -> None:
    """Restore the historical non-unique token-hash index."""
    op.drop_index(
        "ix_refresh_tokens_token_hash",
        table_name="refresh_tokens",
    )
    op.create_index(
        "ix_refresh_tokens_token_hash",
        "refresh_tokens",
        ["token_hash"],
        unique=False,
    )
