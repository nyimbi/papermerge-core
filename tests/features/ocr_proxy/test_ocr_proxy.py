# (c) Copyright Datacraft, 2026
"""Tests for the OCR proxy endpoint (OpenAI-compatible LiteLLM passthrough)."""
import os
import uuid
from unittest.mock import MagicMock, patch, AsyncMock

os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from papermerge.core.features.ocr_proxy.router import router as ocr_proxy_router
from papermerge.core.features.auth import get_current_user


def _make_user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    u.scopes = []
    return u


_user = _make_user()
app = FastAPI()
app.include_router(ocr_proxy_router)
app.dependency_overrides[get_current_user] = lambda: _user
client = TestClient(app, raise_server_exceptions=False)


def test_openai_chat_returns_service_unavailable_when_unconfigured():
    """POST /ocr-proxy/openai/chat/completions without LiteLLM config → 503."""
    response = client.post("/ocr-proxy/openai/chat/completions", json={})
    assert response.status_code == 503

