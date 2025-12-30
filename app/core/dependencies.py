"""
Authentication dependencies.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.token_blacklist import token_blacklist
from app.db.session import get_db
from app.db.models import User

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
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
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )

        jti: str = payload.get("jti")
        user_id: str = payload.get("sub")
        token_version: int = payload.get("token_version")

        if user_id is None or jti is None:
            raise credentials_exception

        # Check if token is blacklisted
        if await token_blacklist.is_blacklisted(jti):
            raise revoked_exception

    except JWTError:
        raise credentials_exception

    # Fetch user from database
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception

    # Check token version (logout-all-devices support)
    if token_version is not None and user.token_version != token_version:
        raise revoked_exception

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Ensure user is active.
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )
    return current_user
