"""Basic health check tests."""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_app_starts():
    """Test that the app starts without errors."""
    assert app is not None


def test_docs_endpoint():
    """Test that /docs endpoint returns 200."""
    response = client.get("/docs")
    assert response.status_code == 200
