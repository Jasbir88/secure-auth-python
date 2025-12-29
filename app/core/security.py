"""
Security utilities for authentication.
"""
from datetime import datetime, timedelta
import secrets
import hashlib
import uuid

from jose import jwt, JWTError

from app.core.config import settings

# Import from your secure-auth package (installed as 'auth')
from auth.password import hash_password, verify_password


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    """Create a new JWT access token with JTI for revocation support."""
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    payload = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.utcnow(),
        "jti": str(uuid.uuid4()),  # Unique token ID for blacklisting
        "type": "access",
    }
    
    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT access token."""
    return jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )


def get_token_payload(token: str) -> dict | None:
    """
    Get token payload without verification.
    Useful for extracting JTI from expired tokens.
    """
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_exp": False},
        )
    except JWTError:
        return None


def hash_user_password(password: str) -> str:
    """Hash a user password using Argon2."""
    return hash_password(password)


def verify_user_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a user password against its hash."""
    return verify_password(plain_password, hashed_password)


def create_refresh_token() -> str:
    """Create a new refresh token (random string)."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    """Hash a refresh token for storage using SHA256."""
    return hashlib.sha256(token.encode()).hexdigest()


def verify_refresh_token(plain_token: str, hashed_token: str) -> bool:
    """Verify a refresh token against its stored hash."""
    return hash_refresh_token(plain_token) == hashed_token
