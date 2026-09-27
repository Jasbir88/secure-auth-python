"""
Authentication dependencies.
"""

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import PyJWTError
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.models import User
from app.db.session import get_db

security = HTTPBearer()


async def get_current_user(
    request: Request,  # Add request to access app.state
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """
    Validate access token and check blacklist before returning user.
    """
    token = credentials.credentials

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    revoked_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token has been revoked",
        headers={"WWW-Authenticate": "Bearer"},
    )

    revocation_unavailable_exception = HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Authentication service temporarily unavailable",
    )

    try:
        payload = decode_access_token(token)

        jti: str = payload["jti"]
        user_id: str = payload["sub"]
        token_version: int = payload["token_version"]

        # Revocation state is security-critical. Never bypass it when
        # Redis or the blacklist service is unavailable.
        token_blacklist = getattr(
            request.app.state,
            "token_blacklist",
            None,
        )
        if token_blacklist is None:
            raise revocation_unavailable_exception

        try:
            is_blacklisted = await token_blacklist.is_blacklisted(jti)
        except RedisError as exc:
            raise revocation_unavailable_exception from exc

        if is_blacklisted:
            raise revoked_exception

    except PyJWTError:
        raise credentials_exception

    # Fetch user from database
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise revoked_exception

    # Check token version (logout-all-devices support)
    if user.token_version != token_version:
        raise revoked_exception

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Ensure user is active.
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user"
        )
    return current_user
