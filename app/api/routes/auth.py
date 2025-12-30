"""
Authentication routes.
"""
from datetime import datetime, timedelta, timezone

# Instead of:
datetime.utcnow()

# Use:
datetime.now(timezone.utc)

from app.core.dependencies import get_current_user

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi_limiter.depends import RateLimiter
from sqlalchemy.orm import Session
from sqlalchemy import and_
from jose import jwt, JWTError

from app.db.models import User, RefreshToken
from app.db.session import get_db
from app.schemas.auth import (
    RegisterRequest,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_user_password,
    verify_user_password,
    hash_refresh_token,
)
from app.core.config import settings

router = APIRouter(prefix="/auth", tags=["Authentication"])
security = HTTPBearer()


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RateLimiter(times=5, seconds=60))]
)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new user."""
    existing_user = db.query(User).filter(User.email == payload.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(
        email=payload.email,
        password_hash=hash_user_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    access_token = create_access_token(str(user.id), user.token_version)
    refresh_token_value = create_refresh_token()

    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(refresh_token_value),
            expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )
    )
    db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token_value,
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(RateLimiter(times=5, seconds=60))]
)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """Login with email and password."""
    user = db.query(User).filter(User.email == payload.email).first()

    if not user or not verify_user_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    access_token = create_access_token(str(user.id), user.token_version)
    refresh_token_value = create_refresh_token()

    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(refresh_token_value),
            expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )
    )
    db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token_value,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    dependencies=[Depends(RateLimiter(times=10, seconds=60))]
)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    """Refresh access token using refresh token."""
    hashed = hash_refresh_token(payload.refresh_token)

    token = (
        db.query(RefreshToken)
        .filter(
            and_(
                RefreshToken.token_hash == hashed,
                RefreshToken.revoked == False,
                RefreshToken.expires_at > datetime.utcnow(),
            )
        )
        .first()
    )

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    token.revoked = True

    user = db.query(User).filter(User.id == token.user_id).first()
    new_access = create_access_token(str(token.user_id), user.token_version)
    new_refresh = create_refresh_token()

    db.add(
        RefreshToken(
            user_id=token.user_id,
            token_hash=hash_refresh_token(new_refresh),
            expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )
    )
    db.commit()

    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
    )


@router.post(
    "/logout",
    dependencies=[Depends(RateLimiter(times=10, seconds=60))]
)
async def logout(
    request: Request,
    payload: RefreshRequest,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Logout - revoke refresh token AND blacklist access token."""
    # 1. Revoke refresh token
    hashed = hash_refresh_token(payload.refresh_token)
    db_token = db.query(RefreshToken).filter(RefreshToken.token_hash == hashed).first()

    if db_token:
        db_token.revoked = True
        db.commit()

    # 2. Blacklist access token
    access_token = credentials.credentials
    try:
        token_payload = jwt.decode(
            access_token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        jti = token_payload.get("jti")
        exp = token_payload.get("exp")

        if jti and exp:
            # Use the token_blacklist from app.state
            await request.app.state.token_blacklist.add(jti, exp)

    except JWTError:
        pass  # Token invalid but still revoke refresh token

    return {"message": "Successfully logged out"}


@router.post(
    "/logout-all",
    dependencies=[Depends(RateLimiter(times=5, seconds=60))]
)
async def logout_all_devices(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Logout from all devices by incrementing token_version."""
    # Increment token version - invalidates all existing tokens
    current_user.token_version += 1
    
    # Also revoke all refresh tokens
    db.query(RefreshToken).filter(
        RefreshToken.user_id == current_user.id,
        RefreshToken.revoked == False
    ).update({"revoked": True})
    
    db.commit()
    
    return {"message": "All sessions invalidated"}
