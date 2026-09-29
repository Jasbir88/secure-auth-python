"""Tests for one-time authentication action-token primitives."""

from app.core.security import (
    create_auth_action_token,
    hash_auth_action_token,
)


def test_auth_action_tokens_are_random() -> None:
    first = create_auth_action_token()
    second = create_auth_action_token()

    assert first
    assert second
    assert first != second


def test_auth_action_token_hash_is_deterministic_and_not_plaintext() -> None:
    token = create_auth_action_token()

    first_hash = hash_auth_action_token(token)
    second_hash = hash_auth_action_token(token)

    assert first_hash == second_hash
    assert first_hash != token
    assert len(first_hash) == 64
