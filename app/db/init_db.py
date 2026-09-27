"""Database connectivity and schema verification helper."""

import logging

from sqlalchemy import text

from app.db.schema import verify_database_schema
from app.db.session import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init_db():
    """Verify that Alembic has prepared the database schema."""
    logger.info("Verifying Alembic-managed database schema...")
    verify_database_schema()
    logger.info("Database schema verified successfully!")


def check_db_connection():
    """Verify database connection."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection successful!")
        return True
    except Exception as exc:
        logger.error("Database connection failed: %s", exc)
        return False


if __name__ == "__main__":
    if check_db_connection():
        init_db()
