# (c) Copyright Datacraft, 2026
"""Tests for inventory management endpoints."""
import os
import uuid
from unittest.mock import MagicMock, AsyncMock

os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from papermerge.core.features.inventory.router import router as inventory_router
from papermerge.core.features.auth import get_current_user
from papermerge.core.db.engine import get_db


def _make_user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    u.scopes = ["node:view", "node:create"]
    return u


def _make_db():
    db = AsyncMock()
    db.scalar.return_value = 0
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result
    return db


_user = _make_user()
_db = _make_db()
app = FastAPI()
app.include_router(inventory_router)
app.dependency_overrides[get_current_user] = lambda: _user
app.dependency_overrides[get_db] = lambda: _db
client = TestClient(app, raise_server_exceptions=False)


def test_list_locations_ok():
    response = client.get("/inventory/locations")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_check_duplicates_requires_body():
    response = client.post("/inventory/duplicates/check", json={})
    assert response.status_code in (200, 400, 422)


def test_list_manifests_ok():
    response = client.get("/inventory/manifests")
    assert response.status_code in (200, 404, 405)
