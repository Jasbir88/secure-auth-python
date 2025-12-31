import sys
import os

# Add project root to Python path FIRST
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set testing mode and database URL BEFORE importing app modules
os.environ["TESTING"] = "1"
if not os.getenv("USE_DOCKER_DB"):
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Now import app modules (after setting environment variables)
from app.db.session import Base
from app.db.models import User, RefreshToken  # Register models with Base
from app.main import app
from app.deps import get_db


def get_test_database_url():
    """Get database URL based on environment."""
    if os.getenv("USE_DOCKER_DB"):
        return os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/test_db")
    return os.getenv("DATABASE_URL", "sqlite:///:memory:")


TEST_DATABASE_URL = get_test_database_url()
IS_SQLITE = TEST_DATABASE_URL.startswith("sqlite")

# Configure engine based on database type
if IS_SQLITE:
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Enable foreign key support for SQLite
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
else:
    engine = create_engine(TEST_DATABASE_URL)

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session():
    """Creates a fresh database session for each test."""
    Base.metadata.create_all(bind=engine)

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    """Test client with database dependency override."""
    from fastapi.testclient import TestClient

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
