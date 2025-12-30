"""
User schemas for API responses.
"""
from pydantic import BaseModel, ConfigDict, EmailStr
from uuid import UUID
from datetime import datetime


class UserResponse(BaseModel):
    """Public user information."""
    id: UUID
    email: EmailStr
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserProfileResponse(BaseModel):
    """Detailed user profile."""
    id: UUID
    email: EmailStr
    is_active: bool
    created_at: datetime
    # Add more fields as needed

    model_config = ConfigDict(from_attributes=True)


class UpdateProfileRequest(BaseModel):
    """Request to update user profile."""
    email: EmailStr | None = None


class ChangePasswordRequest(BaseModel):
    """Request to change password."""
    current_password: str
    new_password: str
