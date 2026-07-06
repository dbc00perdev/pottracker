"""Unit tests for hashing + JWT — no DB, no marker."""

from __future__ import annotations

import pytest
from jose import JWTError

from apps.tooling.api.config import Settings
from apps.tooling.api.security import (
    JWT_PAYLOAD_VERSION,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

_S = Settings(database_url="", jwt_secret="unit-secret", jwt_access_ttl=900,
              jwt_refresh_ttl=86400, log_level="INFO")


def test_hash_roundtrip():
    h = hash_password("hunter2")
    assert h != "hunter2"
    assert verify_password("hunter2", h)
    assert not verify_password("wrong", h)


def test_verify_malformed_hash_is_false():
    assert verify_password("x", "not-a-bcrypt-hash") is False


def test_access_token_roundtrip():
    tok = create_access_token(_S, user_id="u1", username="bob", role="setter")
    payload = decode_token(_S, tok)
    assert payload["sub"] == "u1"
    assert payload["role"] == "setter"
    assert payload["typ"] == "access"
    assert payload["ver"] == JWT_PAYLOAD_VERSION


def test_refresh_token_typed():
    payload = decode_token(_S, create_refresh_token(_S, user_id="u1"))
    assert payload["typ"] == "refresh"


def test_wrong_secret_rejected():
    tok = create_access_token(_S, user_id="u1", username="b", role="viewer")
    other = Settings(database_url="", jwt_secret="different", jwt_access_ttl=900,
                     jwt_refresh_ttl=86400, log_level="INFO")
    with pytest.raises(JWTError):
        decode_token(other, tok)


def test_expired_token_rejected():
    # Negative TTL → exp already in the past; deterministic, no sleep.
    s = Settings(database_url="", jwt_secret="s", jwt_access_ttl=-5,
                 jwt_refresh_ttl=-5, log_level="INFO")
    tok = create_access_token(s, user_id="u1", username="b", role="viewer")
    with pytest.raises(JWTError):
        decode_token(s, tok)


def test_version_mismatch_rejected(monkeypatch):
    tok = create_access_token(_S, user_id="u1", username="b", role="viewer")
    monkeypatch.setattr("apps.tooling.api.security.JWT_PAYLOAD_VERSION", 999)
    with pytest.raises(JWTError):
        decode_token(_S, tok)
