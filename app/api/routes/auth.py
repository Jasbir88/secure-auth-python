"""
Authentication routes.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi_limiter.depends import RateLimiter
from sqlalchemy.orm import Session
from sqlalchemy import and_

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

    access_token = create_access_token(str(user.id))
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
    
    access_token = create_access_token(str(user.id))
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

    new_access = create_access_token(str(token.user_id))
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
def logout(payload: RefreshRequest, db: Session = Depends(get_db)):
    """Logout - revoke refresh token."""
    hashed = hash_refresh_token(payload.refresh_token)
    token = db.query(RefreshToken).filter(RefreshToken.token_hash == hashed).first()
    
    if token:
        token.revoked = True
        db.commit()
    
    return {"message": "Successfully logged out"}
