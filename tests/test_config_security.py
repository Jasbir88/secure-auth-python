"""Startup policy for JWT settings; all keys here are test fixtures."""

import pytest
from pydantic import ValidationError

from app.core.config import DEFAULT_JWT_SECRET, Settings

TEST_SECRET = "test-only-settings-key-0123456789-abcdef"


@pytest.fixture(autouse=True)
def isolate_jwt_environment(monkeypatch):
    for name in (
        "ENVIRONMENT",
        "JWT_SECRET_KEY",
        "JWT_ALGORITHM",
        "JWT_ISSUER",
        "JWT_AUDIENCE",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    "secret",
    [
        DEFAULT_JWT_SECRET,
        "",
        " " * 64,
        "short-test-key",
        "s" * 31,
        " " + TEST_SECRET,
        DEFAULT_JWT_SECRET + " ",
    ],
)
def test_production_rejects_unsafe_secret(secret):
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(_env_file=None, ENVIRONMENT="production", JWT_SECRET_KEY=secret)


def test_production_rejects_missing_secret():
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(_env_file=None, ENVIRONMENT="production")


@pytest.mark.parametrize("secret", ["0123456789abcdef" * 2, "é" * 16])
def test_production_accepts_32_utf8_bytes(secret):
    # This checks the byte-length boundary, not the randomness of a key.
    configured = Settings(
        _env_file=None, ENVIRONMENT="production", JWT_SECRET_KEY=secret
    )
    assert configured.JWT_SECRET_KEY == secret


@pytest.mark.parametrize("environment", ["development", "test"])
def test_nonproduction_can_use_default_secret(environment):
    configured = Settings(_env_file=None, ENVIRONMENT=environment)
    assert configured.JWT_SECRET_KEY == DEFAULT_JWT_SECRET


@pytest.mark.parametrize("field", ["JWT_ISSUER", "JWT_AUDIENCE"])
@pytest.mark.parametrize("value", ["", "   "])
def test_rejects_empty_token_identity(field, value):
    with pytest.raises(ValidationError, match=field):
        Settings(_env_file=None, **{field: value})


def test_environment_typo_does_not_silently_disable_validation():
    with pytest.raises(ValidationError, match="ENVIRONMENT"):
        Settings(_env_file=None, ENVIRONMENT="prod")


def test_validation_messages_and_repr_hide_secret_values():
    short_secret = "test-input-must-not-be-echoed"
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, ENVIRONMENT="production", JWT_SECRET_KEY=short_secret)
    assert short_secret not in str(error.value)
    configured = Settings(
        _env_file=None, ENVIRONMENT="production", JWT_SECRET_KEY=TEST_SECRET
    )
    assert TEST_SECRET not in repr(configured)
