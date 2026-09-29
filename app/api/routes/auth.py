"""
Authentication routes.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.core.rate_limit import RateLimiter
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from auth.validator import is_valid_password

from app.core.auth_actions import (
    EMAIL_VERIFICATION_PURPOSE,
    PASSWORD_RESET_PURPOSE,
    consume_auth_action_token,
    invalidate_auth_action_tokens,
    issue_auth_action_token,
)
from app.core.config import settings
from app.core.dependencies import get_current_user
from app.core.email_delivery import EmailDeliveryError
from app.core.sessions import revoke_active_refresh_tokens
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    create_refresh_token,
    get_token_payload,
    hash_refresh_token,
    hash_user_password,
    verify_user_password,
)
from app.db.models import RefreshToken, User, utc_now_naive
from app.db.session import get_db
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    TokenResponse,
    VerifyEmailRequest,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])
security = HTTPBearer()


@router.post(
    "/register",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RateLimiter(times=5, seconds=60))],
)
def register(
    request: Request,
    payload: RegisterRequest,
    db: Session = Depends(get_db),
):
    """Register an unverified user and send a verification token."""
    if not is_valid_password(payload.password):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid registration data",
        )

    existing_user = db.query(User).filter(User.email == payload.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(
        email=payload.email,
        password_hash=hash_user_password(payload.password),
        email_verified_at=None,
    )
    db.add(user)
    db.flush()

    raw_token = issue_auth_action_token(
        db,
        user,
        purpose=EMAIL_VERIFICATION_PURPOSE,
        expires_in=timedelta(
            hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS,
        ),
    )

    # Commit before the external SMTP side effect. If delivery fails, the
    # account remains safely unverified and /resend-verification can recover.
    db.commit()

    email_sender = request.app.state.email_sender

    try:
        email_sender.send_verification(
            recipient=user.email,
            token=raw_token,
            expires_hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS,
        )
    except EmailDeliveryError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Verification email could not be delivered",
        ) from exc

    return MessageResponse(
        message="Registration successful. Check your email to verify your account."
    )


@router.post(
    "/verify-email",
    response_model=MessageResponse,
    dependencies=[Depends(RateLimiter(times=10, seconds=60))],
)
def verify_email(
    payload: VerifyEmailRequest,
    db: Session = Depends(get_db),
):
    """Verify an email address with a one-time token."""
    token = consume_auth_action_token(
        db,
        payload.token,
        purpose=EMAIL_VERIFICATION_PURPOSE,
    )

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token",
        )

    user = db.query(User).filter(User.id == token.user_id).with_for_update().first()

    if user is None or not user.is_active:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token",
        )

    user.email_verified_at = utc_now_naive()

    # A newly verified email identity must not inherit recovery tokens
    # issued for an earlier identity state.
    invalidate_auth_action_tokens(
        db,
        user,
        purpose=PASSWORD_RESET_PURPOSE,
    )

    db.commit()

    return MessageResponse(message="Email verified successfully")


@router.post(
    "/resend-verification",
    response_model=MessageResponse,
    dependencies=[Depends(RateLimiter(times=3, seconds=60))],
)
def resend_verification(
    request: Request,
    payload: ResendVerificationRequest,
    db: Session = Depends(get_db),
):
    """Resend verification without revealing account existence."""
    generic = MessageResponse(
        message=("If an eligible account exists, a verification email has been sent.")
    )

    user = db.query(User).filter(User.email == payload.email).first()

    if user is None or not user.is_active or user.email_verified_at is not None:
        return generic

    raw_token = issue_auth_action_token(
        db,
        user,
        purpose=EMAIL_VERIFICATION_PURPOSE,
        expires_in=timedelta(
            hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS,
        ),
    )
    db.commit()

    try:
        request.app.state.email_sender.send_verification(
            recipient=user.email,
            token=raw_token,
            expires_hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS,
        )
    except EmailDeliveryError:
        # Preserve the same outward response to avoid account enumeration.
        pass

    return generic


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    dependencies=[Depends(RateLimiter(times=3, seconds=60))],
)
def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    """Issue password-reset recovery without revealing account existence."""
    generic = MessageResponse(
        message=(
            "If an eligible account exists, " "a password reset email has been sent."
        )
    )

    # Lock the identity before checking eligibility so an email or
    # credential change cannot race reset-token issuance.
    user = db.query(User).filter(User.email == payload.email).with_for_update().first()

    if user is None or not user.is_active or user.email_verified_at is None:
        return generic

    raw_token = issue_auth_action_token(
        db,
        user,
        purpose=PASSWORD_RESET_PURPOSE,
        expires_in=timedelta(
            minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES,
        ),
    )

    # Persist before SMTP. If delivery fails, a later request replaces
    # this undelivered token without exposing account state.
    db.commit()

    try:
        request.app.state.email_sender.send_password_reset(
            recipient=user.email,
            token=raw_token,
            expires_minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES,
        )
    except EmailDeliveryError:
        pass

    return generic


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    dependencies=[Depends(RateLimiter(times=5, seconds=60))],
)
def reset_password(
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    """Reset a password using a valid one-time recovery token."""
    # Check policy before consuming the token. A weak-password mistake
    # must not destroy an otherwise valid recovery token.
    if not is_valid_password(payload.new_password):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid password data",
        )

    token = consume_auth_action_token(
        db,
        payload.token,
        purpose=PASSWORD_RESET_PURPOSE,
    )

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired password reset token",
        )

    user = db.query(User).filter(User.id == token.user_id).with_for_update().first()

    if user is None or not user.is_active or user.email_verified_at is None:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired password reset token",
        )

    user.password_hash = hash_user_password(payload.new_password)

    # Kill all sessions created with the old credential.
    user.token_version += 1
    revoke_active_refresh_tokens(db, user.id)

    db.commit()

    return MessageResponse(message="Password reset successfully")


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

    if user.email_verified_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email verification required",
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
    """Rotate a refresh token and detect reuse of rotated tokens."""
    hashed = hash_refresh_token(payload.refresh_token)

    # PostgreSQL serializes concurrent rotations of the same token here.
    # SQLite ignores FOR UPDATE, which is sufficient for sequential tests.
    token = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == hashed)
        .with_for_update()
        .first()
    )

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # A revoked token that has a replacement was previously rotated.
    # Seeing it again is refresh-token reuse, so revoke only its family.
    if token.revoked:
        if token.replaced_by_token_id is not None:
            db.query(RefreshToken).filter(
                RefreshToken.family_id == token.family_id,
                RefreshToken.revoked.is_(False),
            ).update({"revoked": True}, synchronize_session=False)
            db.commit()

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # DateTime is timezone-naive on some supported database backends.
    now = datetime.now(timezone.utc)
    expires_at = token.expires_at
    if expires_at.tzinfo is None:
        now = now.replace(tzinfo=None)

    if expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user = db.query(User).filter(User.id == token.user_id).first()
    if user is None or not user.is_active or user.email_verified_at is None:
        if user is not None:
            revoke_active_refresh_tokens(db, user.id)
            db.commit()

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    new_access = create_access_token(str(token.user_id), user.token_version)
    new_refresh = create_refresh_token()

    new_token = RefreshToken(
        user_id=token.user_id,
        family_id=token.family_id,
        token_hash=hash_refresh_token(new_refresh),
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(new_token)
    db.flush()

    token.revoked = True
    token.replaced_by_token_id = new_token.id

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
        token_blacklist = getattr(
            request.app.state,
            "token_blacklist",
            None,
        )

        if token_blacklist is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service temporarily unavailable",
            )

        try:
            await token_blacklist.add(
                token_payload["jti"],
                token_payload["exp"],
            )
        except RedisError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service temporarily unavailable",
            ) from exc

    return {"message": "Successfully logged out"}


@router.post("/logout-all", dependencies=[Depends(RateLimiter(times=5, seconds=60))])
async def logout_all_devices(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Logout from all devices by incrementing token_version."""
    current_user.token_version += 1

    revoke_active_refresh_tokens(db, current_user.id)

    db.commit()

    return {"message": "All sessions invalidated"}
