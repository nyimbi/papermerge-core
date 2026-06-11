# (c) Copyright Datacraft, 2026
"""Tests for dashboard stats and activity endpoints."""
import os
import uuid
from unittest.mock import MagicMock, AsyncMock

os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from papermerge.core.features.dashboard.router import router as dashboard_router
from papermerge.core.features.auth import get_current_user
from papermerge.core.db.engine import get_db


def _make_user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    u.username = "testuser"
    u.email = "test@example.com"
    u.is_superuser = False
    u.scopes = ["node:view"]
    return u


def _make_db():
    db = AsyncMock()
    db.scalar.return_value = 0
    db.get.return_value = None  # no tenant → quota falls back to 10 GB default
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    db.execute.return_value = result_mock
    return db


_user = _make_user()
_db = _make_db()

app = FastAPI()
app.include_router(dashboard_router)
app.dependency_overrides[get_current_user] = lambda: _user
app.dependency_overrides[get_db] = lambda: _db

client = TestClient(app)


def test_dashboard_stats_ok():
    response = client.get("/dashboard/stats")
    assert response.status_code == 200
    data = response.json()
    assert "totalDocuments" in data
    assert "storageUsedBytes" in data
    assert "pendingTasks" in data
    assert isinstance(data["totalDocuments"], int)


def test_dashboard_stats_has_quota():
    response = client.get("/dashboard/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["storageQuotaBytes"] == 10737418240  # 10 GB


def test_dashboard_activity_ok():
    response = client.get("/dashboard/activity")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)


def test_dashboard_activity_limit_param():
    response = client.get("/dashboard/activity?limit=5")
    assert response.status_code == 200


def test_dashboard_requires_auth():
    """Without auth override, unauthenticated request should be rejected."""
    bare_app = FastAPI()
    bare_app.include_router(dashboard_router)
    bare_client = TestClient(bare_app, raise_server_exceptions=False)
    response = bare_client.get("/dashboard/stats")
    assert response.status_code in (401, 403, 422)
