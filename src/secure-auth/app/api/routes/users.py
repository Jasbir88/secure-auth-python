"""
Protected user routes - require authentication.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi_limiter.depends import RateLimiter
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.core.security import hash_user_password, verify_user_password
from app.db.session import get_db
from app.db.models import User
from app.schemas.user import (
    UserResponse,
    UserProfileResponse,
    UpdateProfileRequest,
    ChangePasswordRequest,
)

router = APIRouter(prefix="/api/users", tags=["Users"])


@router.get(
    "/me",
    response_model=UserProfileResponse,
    dependencies=[Depends(RateLimiter(times=30, seconds=60))]
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
    dependencies=[Depends(RateLimiter(times=10, seconds=60))]
)
async def update_profile(
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
    
    db.commit()
    db.refresh(current_user)
    
    return current_user


@router.post(
    "/me/change-password",
    dependencies=[Depends(RateLimiter(times=3, seconds=60))]
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
    
    # Update password
    current_user.password_hash = hash_user_password(payload.new_password)
    db.commit()
    
    return {"message": "Password changed successfully"}


@router.delete(
    "/me",
    dependencies=[Depends(RateLimiter(times=3, seconds=60))]
)
async def delete_account(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Deactivate current user's account.
    This performs a soft delete (sets is_active to False).
    """
    current_user.is_active = False
    db.commit()
    
    return {"message": "Account deactivated successfully"}
