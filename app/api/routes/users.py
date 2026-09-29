"""
Protected user routes - require authentication.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from app.core.rate_limit import RateLimiter
from sqlalchemy.orm import Session

from auth.validator import is_valid_password

from app.core.auth_actions import (
    EMAIL_VERIFICATION_PURPOSE,
    PASSWORD_RESET_PURPOSE,
    invalidate_auth_action_tokens,
    issue_auth_action_token,
)
from app.core.config import settings
from app.core.dependencies import get_current_user
from app.core.email_delivery import EmailDeliveryError
from app.core.security import hash_user_password, verify_user_password
from app.core.sessions import revoke_active_refresh_tokens
from app.db.session import get_db
from app.db.models import User
from app.schemas.user import (
    UserProfileResponse,
    UpdateProfileRequest,
    ChangePasswordRequest,
)

router = APIRouter(prefix="/users", tags=["Users"])


@router.get(
    "/me",
    response_model=UserProfileResponse,
    dependencies=[Depends(RateLimiter(times=30, seconds=60))],
)
async def get_current_user_profile(
    current_user: User = Depends(get_current_user),
):
    """
    Get current authenticated user's profile.
    Requires valid JWT access token.
    """
    return current_user


@router.patch(
    "/me",
    response_model=UserProfileResponse,
    dependencies=[Depends(RateLimiter(times=10, seconds=60))],
)
async def update_profile(
    request: Request,
    payload: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update current user's profile.
    """
    if payload.email and payload.email != current_user.email:
        # Check if email is already taken
        existing = db.query(User).filter(User.email == payload.email).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already in use",
            )
        current_user.email = payload.email
        current_user.email_verified_at = None

        # An email identity change invalidates every existing session.
        current_user.token_version += 1
        revoke_active_refresh_tokens(db, current_user.id)

        # Recovery sent to the previous email identity must stop working.
        invalidate_auth_action_tokens(
            db,
            current_user,
            purpose=PASSWORD_RESET_PURPOSE,
        )

        raw_token = issue_auth_action_token(
            db,
            current_user,
            purpose=EMAIL_VERIFICATION_PURPOSE,
            expires_in=timedelta(
                hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS,
            ),
        )

        # Persist the identity change before attempting external delivery.
        # If SMTP fails, resend-verification remains a recovery path.
        db.commit()

        try:
            request.app.state.email_sender.send_verification(
                recipient=current_user.email,
                token=raw_token,
                expires_hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS,
            )
        except EmailDeliveryError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Verification email could not be delivered",
            ) from exc

        db.refresh(current_user)
        return current_user

    db.commit()
    db.refresh(current_user)

    return current_user


@router.post(
    "/me/change-password", dependencies=[Depends(RateLimiter(times=3, seconds=60))]
)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Change current user's password.
    Rate limited: 3 requests per 60 seconds.
    """
    # Verify current password
    if not verify_user_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    if not is_valid_password(payload.new_password):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid password data",
        )

    # A credential change also invalidates outstanding recovery links.
    invalidate_auth_action_tokens(
        db,
        current_user,
        purpose=PASSWORD_RESET_PURPOSE,
    )

    # A credential change invalidates every existing session.
    current_user.password_hash = hash_user_password(payload.new_password)
    current_user.token_version += 1
    revoke_active_refresh_tokens(db, current_user.id)
    db.commit()

    return {"message": "Password changed successfully"}


@router.delete("/me", dependencies=[Depends(RateLimiter(times=3, seconds=60))])
async def delete_account(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Deactivate current user's account.
    This performs a soft delete (sets is_active to False).
    """
    current_user.is_active = False
    current_user.token_version += 1
    revoke_active_refresh_tokens(db, current_user.id)
    db.commit()

    return {"message": "Account deactivated successfully"}
