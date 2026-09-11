"""
Authentication dependencies.
"""

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import PyJWTError
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

    try:
        payload = decode_access_token(token)

        jti: str = payload["jti"]
        user_id: str = payload["sub"]
        token_version: int = payload["token_version"]

        # Check if token is blacklisted (use app.state.token_blacklist)
        token_blacklist = request.app.state.token_blacklist
        if token_blacklist and await token_blacklist.is_blacklisted(jti):
            raise revoked_exception

    except PyJWTError:
        raise credentials_exception

    # Fetch user from database
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception

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
