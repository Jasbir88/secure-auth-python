"""Safely prepare the application database with Alembic.

Fresh databases are migrated from base to head.

Tracked databases are upgraded normally.

Legacy databases created by SQLAlchemy before Alembic became authoritative
are adopted only when their schema exactly matches a known historical
revision. Unknown or partial schemas fail closed and are never stamped.
"""

from __future__ import annotations

# ruff: noqa: E402

import sys
from pathlib import Path

# Running this file directly sets sys.path[0] to ./scripts.
# Add the repository root so imports from app.* work locally,
# in Docker, and in GitHub Actions.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from app.core.config import settings
from app.db import models  # noqa: F401
from app.db.session import Base, engine
from app.db.types import GUID

BASE_SCHEMA_REVISION = "2b7c4e1a9d03"
TOKEN_VERSION_REVISION = "5e3526e9e493"
FAMILY_TRACKING_REVISION = "c4f2e8a91b7d"
REFRESH_HASH_UNIQUE_REVISION = "8a7d3f91c2e6"

APP_TABLES = {"users", "refresh_tokens"}
VERSION_TABLE = "alembic_version"


def alembic_config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    return config


def historical_metadata(revision: str) -> sa.MetaData:
    """Build an exact metadata snapshot for a known pre-head revision."""
    metadata = sa.MetaData()

    user_columns: list[sa.Column] = [
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    ]

    if revision in {
        TOKEN_VERSION_REVISION,
        FAMILY_TRACKING_REVISION,
        REFRESH_HASH_UNIQUE_REVISION,
    }:
        user_columns.append(sa.Column("token_version", sa.Integer(), nullable=False))

    users = sa.Table("users", metadata, *user_columns)
    sa.Index("ix_users_email", users.c.email, unique=True)

    refresh_token_columns: list[sa.Column] = [
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
    ]

    if revision in {
        FAMILY_TRACKING_REVISION,
        REFRESH_HASH_UNIQUE_REVISION,
    }:
        refresh_token_columns.extend(
            [
                sa.Column("family_id", GUID(), nullable=False),
                sa.Column("replaced_by_token_id", GUID(), nullable=True),
            ]
        )

    refresh_token_columns.extend(
        [
            sa.Column("token_hash", sa.String(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("revoked", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        ]
    )

    refresh_tokens = sa.Table(
        "refresh_tokens",
        metadata,
        *refresh_token_columns,
    )

    sa.Index(
        "ix_refresh_tokens_token_hash",
        refresh_tokens.c.token_hash,
        unique=revision == REFRESH_HASH_UNIQUE_REVISION,
    )

    if revision in {
        FAMILY_TRACKING_REVISION,
        REFRESH_HASH_UNIQUE_REVISION,
    }:
        sa.Index(
            "ix_refresh_tokens_family_id",
            refresh_tokens.c.family_id,
            unique=False,
        )

    return metadata


def current_head_revision(config: Config) -> str:
    """Return the repository's sole current Alembic head."""
    heads = ScriptDirectory.from_config(config).get_heads()

    if len(heads) != 1:
        raise RuntimeError("Database preparation requires exactly one Alembic head.")

    return heads[0]


def schema_differences(metadata: sa.MetaData) -> list:
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        return compare_metadata(context, metadata)


def finish_upgrade(config: Config) -> None:
    command.upgrade(config, "head")
    command.check(config)


def main() -> int:
    config = alembic_config()

    try:
        with engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())

        if VERSION_TABLE in tables:
            print("Tracked database detected; upgrading to Alembic head.")
            finish_upgrade(config)
            print("Database preparation: PASS")
            return 0

        present_app_tables = tables & APP_TABLES

        if not present_app_tables:
            print("Fresh database detected; migrating from base to head.")
            finish_upgrade(config)
            print("Database preparation: PASS")
            return 0

        if present_app_tables != APP_TABLES:
            print(
                "ERROR: partial untracked application schema detected; "
                "refusing to stamp.",
                file=sys.stderr,
            )
            return 1

        head_revision = current_head_revision(config)

        candidates = (
            (head_revision, Base.metadata),
            (
                REFRESH_HASH_UNIQUE_REVISION,
                historical_metadata(REFRESH_HASH_UNIQUE_REVISION),
            ),
            (
                FAMILY_TRACKING_REVISION,
                historical_metadata(FAMILY_TRACKING_REVISION),
            ),
            (
                TOKEN_VERSION_REVISION,
                historical_metadata(TOKEN_VERSION_REVISION),
            ),
            (
                BASE_SCHEMA_REVISION,
                historical_metadata(BASE_SCHEMA_REVISION),
            ),
        )

        last_differences: list = []

        for revision, metadata in candidates:
            differences = schema_differences(metadata)
            if not differences:
                print(
                    "Recognized untracked legacy schema at revision "
                    f"{revision}; adopting it."
                )
                command.stamp(config, revision)
                finish_upgrade(config)
                print("Database legacy adoption: PASS")
                return 0

            last_differences = differences

        print(
            "ERROR: untracked database does not match any known schema "
            "revision; refusing to stamp.",
            file=sys.stderr,
        )

        for difference in last_differences[:10]:
            print(f"  {difference}", file=sys.stderr)

        return 1

    except Exception as exc:
        print(
            "ERROR: database preparation failed " f"({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
