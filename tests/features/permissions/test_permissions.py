# (c) Copyright Datacraft, 2026
"""Tests for permissions endpoints."""
import os
import uuid
from unittest.mock import MagicMock, AsyncMock, patch

os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from papermerge.core.features.permissions.router import router as permissions_router
from papermerge.core.features.auth import get_current_user


def _make_user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    u.scopes = ["node:view"]
    return u


_user = _make_user()
app = FastAPI()
app.include_router(permissions_router)
app.dependency_overrides[get_current_user] = lambda: _user
client = TestClient(app)


def test_list_permissions_ok():
    response = client.get("/permissions")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_permissions_by_category_ok():
    response = client.get("/permissions/by-category")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, (list, dict))
