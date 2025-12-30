import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db.session import Base, engine


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_logout_all_invalidates_all_sessions(async_client):
    # Register
    await async_client.post("/auth/register", json={
        "email": "testuser@example.com",
        "password": "SecurePass123!"
    })
    
    # Login twice (simulating 2 devices)
    login1 = await async_client.post("/auth/login", json={
        "email": "testuser@example.com",
        "password": "SecurePass123!"
    })
    token1 = login1.json()["access_token"]
    
    login2 = await async_client.post("/auth/login", json={
        "email": "testuser@example.com",
        "password": "SecurePass123!"
    })
    token2 = login2.json()["access_token"]
    
    # Logout all from device 1
    response = await async_client.post(
        "/auth/logout-all",
        headers={"Authorization": f"Bearer {token1}"}
    )
    assert response.status_code == 200
    
    # Both tokens should now be invalid
    # Try logout-all again with token1 - should fail
    retry1 = await async_client.post(
        "/auth/logout-all",
        headers={"Authorization": f"Bearer {token1}"}
    )
    
    # Try logout-all with token2 - should also fail
    retry2 = await async_client.post(
        "/auth/logout-all",
        headers={"Authorization": f"Bearer {token2}"}
    )
    
    assert retry1.status_code == 401
    assert retry2.status_code == 401


@pytest.mark.asyncio
async def test_logout_all_requires_auth(async_client):
    response = await async_client.post("/auth/logout-all")
    assert response.status_code == 401
