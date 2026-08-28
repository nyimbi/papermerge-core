# (c) Copyright Datacraft, 2026
"""Tests for JWT token creation and validation."""
import os
import time
import pytest

os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")


from papermerge.core.features.auth.router import create_jwt_token
from papermerge.core.features.auth import extract_token_data
from papermerge.core.config.settings import Settings
from papermerge.core import config as cfg_module
from unittest.mock import patch


def _make_settings(**kwargs):
    defaults = dict(
        db_url="postgresql+asyncpg://x:x@localhost/x",
        jwt_secret_key="test-secret",
        csrf_secret_key="test-csrf-secret",
        jwt_algorithm="HS256",
        jwt_expire_hours=1,
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def test_create_jwt_token_returns_three_part_string():
    settings = _make_settings()
    with patch("papermerge.core.features.auth.router.get_settings", return_value=settings):
        token = create_jwt_token("user-1", "alice", "alice@test.com", ["read"])
    parts = token.split(".")
    assert len(parts) == 3, "JWT must have three dot-separated parts"


def test_create_jwt_token_payload_contains_expected_fields():
    settings = _make_settings()
    with patch("papermerge.core.features.auth.router.get_settings", return_value=settings):
        token = create_jwt_token("user-1", "alice", "alice@test.com", ["read", "write"])

    with patch("papermerge.core.features.auth.get_settings", return_value=settings):
        token_data = extract_token_data(token)
    assert token_data is not None
    assert token_data.user_id == "user-1"
    assert token_data.username == "alice"
    assert token_data.email == "alice@test.com"
    assert "read" in token_data.scopes
    assert "write" in token_data.scopes


def test_extract_token_data_returns_none_for_malformed_token():
    result = extract_token_data("notavalidtoken")
    assert result is None


def test_extract_token_data_returns_none_for_two_part_token():
    result = extract_token_data("header.payload")
    assert result is None


def test_expired_token_raises_401():
    from fastapi import HTTPException
    settings = _make_settings(jwt_expire_hours=-1)  # already expired
    with patch("papermerge.core.features.auth.router.get_settings", return_value=settings):
        token = create_jwt_token("user-1", "alice", "alice@test.com", [])

    with patch("papermerge.core.features.auth.get_settings", return_value=settings):
        with pytest.raises(HTTPException) as exc_info:
            extract_token_data(token)
    assert exc_info.value.status_code == 401
    assert "expired" in exc_info.value.detail.lower()


def test_token_without_valid_signature_is_rejected():
    """Forged tokens (e.g. alg:none, or signed with a different key) are rejected."""
    import base64, json

    header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
    payload_data = {"sub": "ext-user", "preferred_username": "ext", "email": "ext@test.com", "scopes": []}
    payload = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b"=").decode()
    token = f"{header}.{payload}.sig"

    result = extract_token_data(token)
    assert result is None


def test_token_signed_with_wrong_key_is_rejected():
    """A token signed with a different key must not be accepted."""
    from papermerge.core.features.auth.router import create_jwt_token
    settings = _make_settings()
    with patch("papermerge.core.features.auth.router.get_settings", return_value=settings):
        token = create_jwt_token("user-1", "alice", "alice@test.com", ["read"])

    # Attacker signs with their own key
    from jose import jwt as _jwt
    forged = _jwt.encode(
        {"sub": "admin", "preferred_username": "admin", "scopes": [], "exp": int(time.time()) + 3600},
        "attacker-key",
        algorithm="HS256",
    )

    # Patch get_settings (used by extract_token_data) to the victim's key
    with patch("papermerge.core.features.auth.get_settings", return_value=settings):
        assert extract_token_data(forged) is None
        assert extract_token_data(token) is not None
