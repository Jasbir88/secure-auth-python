"""
Database initialization script.
"""
import logging
from sqlalchemy import text

from app.db.session import engine, Base
from app.db.models import User, RefreshToken  # Import all models

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init_db():
    """Create all database tables."""
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created successfully!")


def check_db_connection():
    """Verify database connection."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection successful!")
        return True
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False


if __name__ == "__main__":
    if check_db_connection():
        init_db()
