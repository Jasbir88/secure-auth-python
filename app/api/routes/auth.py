"""
Authentication routes.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi_limiter.depends import RateLimiter
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    create_refresh_token,
    get_token_payload,
    hash_refresh_token,
    hash_user_password,
    verify_user_password,
)
from app.db.models import RefreshToken, User
from app.db.session import get_db
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])
security = HTTPBearer()


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RateLimiter(times=5, seconds=60))],
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
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
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
    dependencies=[Depends(RateLimiter(times=5, seconds=60))],
)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """Login with email and password."""
    user = db.query(User).filter(User.email == payload.email).first()

    password_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
    password_valid = verify_user_password(payload.password, password_hash)
    if user is None or not password_valid:
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
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
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
    dependencies=[Depends(RateLimiter(times=10, seconds=60))],
)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    """Refresh access token using refresh token."""
    hashed = hash_refresh_token(payload.refresh_token)

    token = (
        db.query(RefreshToken)
        .filter(
            and_(
                RefreshToken.token_hash == hashed,
                RefreshToken.revoked.is_(False),
                RefreshToken.expires_at > datetime.now(timezone.utc),
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
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )
    )
    db.commit()

    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
    )


@router.post("/logout", dependencies=[Depends(RateLimiter(times=10, seconds=60))])
async def logout(
    request: Request,
    payload: RefreshRequest,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Logout - revoke refresh token AND blacklist access token."""
    hashed = hash_refresh_token(payload.refresh_token)
    db_token = db.query(RefreshToken).filter(RefreshToken.token_hash == hashed).first()

    if db_token:
        db_token.revoked = True
        db.commit()

    access_token = credentials.credentials
    token_payload = get_token_payload(access_token)
    if token_payload is not None:
        await request.app.state.token_blacklist.add(
            token_payload["jti"], token_payload["exp"]
        )

    return {"message": "Successfully logged out"}


@router.post("/logout-all", dependencies=[Depends(RateLimiter(times=5, seconds=60))])
async def logout_all_devices(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Logout from all devices by incrementing token_version."""
    current_user.token_version += 1

    db.query(RefreshToken).filter(
        RefreshToken.user_id == current_user.id, RefreshToken.revoked.is_(False)
    ).update({"revoked": True})

    db.commit()

    return {"message": "All sessions invalidated"}
