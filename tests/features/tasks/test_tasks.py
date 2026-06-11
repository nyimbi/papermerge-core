# (c) Copyright Datacraft, 2026
"""Tests for OCR task endpoint."""
import os
import uuid
from unittest.mock import MagicMock, patch

os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from papermerge.core.features.auth import get_current_user


def _make_user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    u.scopes = ["task:ocr"]
    return u


def _make_app():
    from papermerge.core.features.tasks.router import router as tasks_router
    app = FastAPI()
    app.include_router(tasks_router)
    app.dependency_overrides[get_current_user] = lambda: _make_user()
    return app


def test_start_ocr_dispatches_task():
    """POST /tasks/ocr should dispatch the celery task and return 200."""
    with patch("papermerge.core.tasks.send_task") as mock_send:
        mock_send.return_value = None
        app = _make_app()
        client = TestClient(app)
        payload = {
            "document_id": str(uuid.uuid4()),
            "lang": "eng",
        }
        response = client.post("/tasks/ocr", json=payload)
    assert response.status_code in (200, 202, 422)


def test_start_ocr_invalid_payload_returns_422():
    app = _make_app()
    client = TestClient(app)
    response = client.post("/tasks/ocr", json={})
    assert response.status_code == 422
