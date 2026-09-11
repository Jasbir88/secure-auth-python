"""
Security utilities for authentication.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from jwt.exceptions import InvalidTokenError, PyJWTError

from app.core.config import settings

# Import from your secure-auth package (installed as 'auth')
from auth.password import hash_password, verify_password

_REQUIRED_ACCESS_CLAIMS = (
    "exp",
    "iat",
    "sub",
    "jti",
    "iss",
    "aud",
    "type",
    "token_version",
)


def create_access_token(
    subject: str, token_version: int = 1, expires_delta: timedelta | None = None
) -> str:
    """Create a new JWT access token with JTI for revocation support."""
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    payload = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "jti": str(uuid.uuid4()),
        "type": "access",
        "token_version": token_version,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }

    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def _decode_access_token(token: str, *, verify_exp: bool = True) -> dict:
    """Apply the shared access-token policy, optionally allowing expiry."""
    payload = jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        issuer=settings.JWT_ISSUER,
        audience=settings.JWT_AUDIENCE,
        options={
            "require": list(_REQUIRED_ACCESS_CLAIMS),
            "strict_aud": True,
            "verify_exp": verify_exp,
        },
    )
    if payload["type"] != "access":
        raise InvalidTokenError("Expected an access token")
    if not payload["sub"] or not payload["jti"]:
        raise InvalidTokenError("Token subject and JTI must be non-empty")
    version = payload["token_version"]
    if type(version) is not int or version < 1:
        raise InvalidTokenError("Token version must be a positive integer")
    return payload


def decode_access_token(token: str) -> dict:
    """Validate signature, identity, required claims, and expiry."""
    return _decode_access_token(token)


def get_token_payload(token: str) -> dict | None:
    """
    Validate an access token while allowing expiry for revocation bookkeeping.
    Signature, issuer, audience, and required claims are still checked.
    Protected routes must use decode_access_token instead.
    """
    try:
        return _decode_access_token(token, verify_exp=False)
    except PyJWTError:
        return None


def hash_user_password(password: str) -> str:
    """Hash a user password using Argon2."""
    return hash_password(password)


def verify_user_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a user password against its hash."""
    return verify_password(plain_password, hashed_password)


# One hash per worker, using the same Argon2 parameters as real passwords.
# Missing-user logins verify against it; no dummy hashing occurs per request.
DUMMY_PASSWORD_HASH = hash_user_password(secrets.token_urlsafe(32))


def create_refresh_token() -> str:
    """Create a new refresh token (random string)."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    """Hash a refresh token for storage using SHA256."""
    return hashlib.sha256(token.encode()).hexdigest()


def verify_refresh_token(plain_token: str, hashed_token: str) -> bool:
    """Verify a refresh token against its stored hash."""
    return hash_refresh_token(plain_token) == hashed_token
