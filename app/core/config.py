"""
Application configuration.
"""

from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_JWT_SECRET = "your-super-secret-key-change-in-production-min-32-chars"


class Settings(BaseSettings):
    """Application settings."""

    ENVIRONMENT: Literal["development", "test", "production"] = "development"

    # Database
    DATABASE_URL: str = "postgresql+psycopg2://postgres:postgres@db:5432/auth_db"

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # JWT
    JWT_SECRET_KEY: str = Field(default=DEFAULT_JWT_SECRET, repr=False)
    JWT_ALGORITHM: Literal["HS256"] = "HS256"
    JWT_ISSUER: str = "secure-auth-python"
    JWT_AUDIENCE: str = "secure-auth-api"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # CORS
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:8080",
        "http://127.0.0.1:3000",
    ]

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    @field_validator("JWT_ISSUER", "JWT_AUDIENCE")
    @classmethod
    def validate_token_identity(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError(
                "JWT identity must be non-empty without surrounding spaces"
            )
        return value

    @model_validator(mode="after")
    def validate_production_jwt_secret(self) -> "Settings":
        if self.ENVIRONMENT == "production":
            secret = self.JWT_SECRET_KEY
            if (
                secret.strip() == DEFAULT_JWT_SECRET
                or secret != secret.strip()
                or len(secret.encode("utf-8")) < 32
            ):
                raise ValueError(
                    "JWT_SECRET_KEY must be non-default and contain at least "
                    "32 UTF-8 bytes without surrounding whitespace in production"
                )
        return self

    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=True, hide_input_in_errors=True
    )


settings = Settings()
