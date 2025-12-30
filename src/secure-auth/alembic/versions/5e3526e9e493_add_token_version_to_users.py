"""add_token_version_to_users

Revision ID: 5e3526e9e493
Revises:
Create Date: 2025-12-30 05:29:28.946015

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5e3526e9e493'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add column with server default for existing rows
    op.add_column('users', sa.Column('token_version', sa.Integer(), nullable=False, server_default='1'))
    # Remove server default (keep Python-side default only)
    op.alter_column('users', 'token_version', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'token_version')
