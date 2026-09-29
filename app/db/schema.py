"""Runtime verification for the Alembic-managed database schema."""

from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.db import models  # noqa: F401
from app.db.session import Base, engine


def verify_database_schema() -> None:
    """Fail startup unless the database is at the sole Alembic head."""
    root = Path(__file__).resolve().parents[2]

    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))

    script = ScriptDirectory.from_config(config)
    expected_heads = set(script.get_heads())

    if len(expected_heads) != 1:
        raise RuntimeError("Application requires exactly one Alembic migration head.")

    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        current_heads = set(context.get_current_heads())

        if current_heads != expected_heads:
            raise RuntimeError("Database is not at the required Alembic revision.")

        differences = compare_metadata(context, Base.metadata)

    if differences:
        raise RuntimeError("Database schema differs from application metadata.")
