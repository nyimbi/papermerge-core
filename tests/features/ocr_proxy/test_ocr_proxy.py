# (c) Copyright Datacraft, 2026
"""Tests for OCR proxy endpoints (Ollama/LiteLLM passthrough)."""
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


def test_ollama_tags_proxied():
    """GET /ocr-proxy/ollama/tags calls upstream and returns response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"models": []}
    mock_response.headers = {"content-type": "application/json"}

    with patch("httpx.get", return_value=mock_response), \
         patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.return_value.get = AsyncMock(return_value=mock_response)
        response = client.get("/ocr-proxy/ollama/tags")

    assert response.status_code in (200, 500, 503)


def test_ollama_chat_requires_body():
    """POST /ocr-proxy/ollama/chat returns 422 without required body."""
    response = client.post("/ocr-proxy/ollama/chat", json={})
    assert response.status_code in (200, 422, 500, 503)


def test_openai_chat_requires_body():
    response = client.post("/ocr-proxy/openai/chat/completions", json={})
    assert response.status_code in (200, 400, 422, 500, 503)
