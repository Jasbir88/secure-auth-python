import pytest
import asyncio
from redis import asyncio as aioredis
from fastapi_limiter import FastAPILimiter


@pytest.fixture(scope="session")
def event_loop():
    policy = asyncio.WindowsSelectorEventLoopPolicy()
    asyncio.set_event_loop_policy(policy)
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def setup_redis():
    redis = await aioredis.from_url("redis://localhost:6379", encoding="utf-8")
    await FastAPILimiter.init(redis)
    yield
    await redis.aclose()
