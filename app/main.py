import os
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi_limiter import FastAPILimiter

from app.api.routes.auth import router as auth_router
from app.api.routes.users import router as users_router
from app.core.config import settings
from app.core.middleware import (
    SecurityHeadersMiddleware,
    RequestIDMiddleware,
    RequestLoggingMiddleware,
)
from app.db.session import engine, Base
from app.db.models import User, RefreshToken  # noqa: F401

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Check if we're in testing mode
TESTING = os.getenv("TESTING", "").lower() in ("1", "true", "yes")


class FakeRedis:
    """Fake Redis client for testing without a real Redis server."""

    async def evalsha(self, *args, **kwargs):
        return 0

    async def script_load(self, script):
        return "fake_sha_hash"

    async def close(self):
        pass

    async def ping(self):
        return True


class FakeTokenBlacklist:
    """Fake token blacklist for testing."""

    def __init__(self):
        self._blacklisted = set()

    async def add(self, jti: str, exp: int):
        self._blacklisted.add(jti)

    async def is_blacklisted(self, jti: str) -> bool:
        return jti in self._blacklisted


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown events."""
    logger.info("Starting up...")

    # Initialize database tables
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables ready!")

    if TESTING:
        logger.info("Testing mode: Using fake Redis...")
        fake_redis = FakeRedis()
        await FastAPILimiter.init(fake_redis)
        app.state.redis = fake_redis
        app.state.token_blacklist = FakeTokenBlacklist()
        logger.info("Testing mode: Fake Redis initialized!")
    else:
        logger.info("Connecting to Redis...")
        try:
            import redis.asyncio as aioredis
            from app.core.token_blacklist import TokenBlacklist

            redis_client = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
            await FastAPILimiter.init(redis_client)
            app.state.redis = redis_client
            app.state.token_blacklist = TokenBlacklist(redis_client)
            logger.info("Redis connected!")
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}")
            app.state.redis = None
            app.state.token_blacklist = None

    logger.info("Auth service ready!")
    yield
    logger.info("Shutting down...")
    await FastAPILimiter.close()
    if hasattr(app.state, 'redis') and app.state.redis and not TESTING:
        await app.state.redis.close()


app = FastAPI(
    title="Auth Service API",
    description="""
## Secure Authentication Service

### Features:
- 🔐 JWT-based authentication
- 🔄 Token refresh flow
- 🚪 Logout from all devices
- 🛡️ Rate limiting
- 📝 Token blacklisting

### Authentication:
Use the `Authorization: Bearer <token>` header for protected endpoints.
    """,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    contact={
        "name": "Jasbir Singh",
        "url": "https://github.com/Jasbir88/secure-auth-python",
    },
    license_info={
        "name": "MIT",
    },
)

# Add middleware
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Process-Time"],
)

# Include routers
app.include_router(auth_router)
app.include_router(users_router)


@app.get("/health")
@app.head("/health")
def health():
    """Basic health check."""
    return {"status": "ok"}


@app.get("/health/ready")
@app.head("/health/ready")
async def readiness():
    """Readiness check with dependency status."""
    redis_ok = False
    db_ok = False

    try:
        if TESTING:
            redis_ok = True
        elif app.state.redis:
            await app.state.redis.ping()
            redis_ok = True
    except Exception:
        pass

    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    status = "ready" if (redis_ok and db_ok) else "degraded"
    return {
        "status": status,
        "dependencies": {
            "database": "connected" if db_ok else "disconnected",
            "redis": "connected" if redis_ok else "disconnected",
        }
    }


@app.get("/")
def root():
    """API root."""
    return {
        "service": "Auth Service API",
        "version": "1.0.0",
        "docs": "/docs",
    }
