"""PyJWT access-token policy, including the logout-only expiry exception."""

from datetime import timedelta

import jwt
import pytest
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError

from app.core.config import settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    get_token_payload,
)


def issued_payload():
    return decode_access_token(create_access_token("user-123", token_version=4))


def resign(payload, *, key=None, algorithm="HS256"):
    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY if key is None else key,
        algorithm=algorithm,
    )


def test_token_has_expected_identity_and_session_claims():
    payload = issued_payload()
    assert payload["iss"] == settings.JWT_ISSUER
    assert payload["aud"] == settings.JWT_AUDIENCE
    assert payload["sub"] == "user-123"
    assert payload["type"] == "access"
    assert payload["token_version"] == 4


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("iss", "another-issuer"),
        ("aud", "another-api"),
        ("type", "refresh"),
        ("token_version", "4"),
        ("token_version", True),
        ("token_version", 0),
        ("sub", ""),
        ("jti", ""),
    ],
)
def test_rejects_invalid_claim_values_in_both_decoders(claim, value):
    payload = issued_payload()
    payload[claim] = value
    token = resign(payload)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)
    assert get_token_payload(token) is None


def test_rejects_multi_audience_token():
    payload = issued_payload()
    payload["aud"] = [settings.JWT_AUDIENCE, "another-api"]
    token = resign(payload)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)
    assert get_token_payload(token) is None


@pytest.mark.parametrize(
    "claim", ["exp", "iat", "sub", "jti", "iss", "aud", "type", "token_version"]
)
def test_rejects_missing_required_claim_in_both_decoders(claim):
    payload = issued_payload()
    payload.pop(claim)
    token = resign(payload)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)
    assert get_token_payload(token) is None


def test_only_revocation_helper_allows_expired_access_tokens():
    token = create_access_token("user-123", expires_delta=timedelta(seconds=-60))
    with pytest.raises(ExpiredSignatureError):
        decode_access_token(token)
    assert get_token_payload(token)["sub"] == "user-123"


def test_both_decoders_reject_wrong_signature():
    token = resign(
        issued_payload(), key="different-test-only-signing-key-0123456789abcdef"
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)
    assert get_token_payload(token) is None


def test_both_decoders_reject_algorithm_outside_allowlist():
    token = resign(issued_payload(), algorithm="HS384")
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)
    assert get_token_payload(token) is None


def test_both_decoders_reject_malformed_token():
    with pytest.raises(InvalidTokenError):
        decode_access_token("not-a-jwt")
    assert get_token_payload("not-a-jwt") is None
