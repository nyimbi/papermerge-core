# (c) Copyright Datacraft, 2026
"""Tests for user home page endpoints."""
import os
import uuid
from unittest.mock import MagicMock, AsyncMock

os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from papermerge.core.features.user_home.router import router as user_home_router
from papermerge.core.features.user_home.router import get_service
from papermerge.core.features.user_home.views import UserHomeDataOut, UserInfo, UserStats
from papermerge.core.features.auth import get_current_user
from papermerge.core.db.engine import get_session


def _make_user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    u.scopes = ["node:view"]
    return u


def _make_service():
    svc = AsyncMock()
    svc.get_user_home_data = AsyncMock(return_value=UserHomeDataOut(
        user=UserInfo(id=str(uuid.uuid4()), name="Test User", email="test@example.com"),
        stats=UserStats(),
    ))
    svc._get_workflow_tasks = AsyncMock(return_value=[])
    svc._get_recent_documents = AsyncMock(return_value=[])
    svc._get_favorites = AsyncMock(return_value=[])
    svc._get_notifications = AsyncMock(return_value=[])
    return svc


_user = _make_user()
_service = _make_service()
app = FastAPI()
app.include_router(user_home_router)
app.dependency_overrides[get_current_user] = lambda: _user
app.dependency_overrides[get_service] = lambda: _service
client = TestClient(app, raise_server_exceptions=False)


def test_get_user_home_ok():
    response = client.get("/users/me/home")
    assert response.status_code == 200
    body = response.json()
    assert "user" in body
    assert "stats" in body


def test_get_assigned_tasks_ok():
    response = client.get("/workflows/tasks/assigned")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_get_recent_documents_ok():
    response = client.get("/documents/recent")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_get_favorites_ok():
    response = client.get("/users/me/favorites")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_get_notifications_ok():
    response = client.get("/notifications")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
