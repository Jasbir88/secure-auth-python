"""
FastAPI Auth Service - Main Application
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi_limiter import FastAPILimiter
import redis.asyncio as aioredis
import logging

from app.api.routes.auth import router as auth_router
from app.api.routes.users import router as users_router
from app.core.config import settings
from app.core.middleware import (
    SecurityHeadersMiddleware,
    RequestIDMiddleware,
    RequestLoggingMiddleware,
)
from app.core.token_blacklist import TokenBlacklist
from app.db.session import engine, Base
from app.db.models import User, RefreshToken

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown events."""
    logger.info("Starting up...")
    
    # Initialize database tables
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables ready!")
    
    # Initialize Redis
    logger.info("Connecting to Redis...")
    redis_client = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )
    
    # Initialize rate limiter
    await FastAPILimiter.init(redis_client)
    
    # Initialize token blacklist
    app.state.redis = redis_client
    app.state.token_blacklist = TokenBlacklist(redis_client)
    
    logger.info("Redis connected!")
    logger.info("Auth service ready!")
    
    yield
    
    logger.info("Shutting down...")
    await FastAPILimiter.close()
    await app.state.redis.close()


app = FastAPI(
    title="Auth Service API",
    description="Secure authentication service with JWT tokens",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Add middleware (order matters: first added = outermost)
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
