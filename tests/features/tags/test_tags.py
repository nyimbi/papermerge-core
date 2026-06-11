import os, uuid
from unittest.mock import MagicMock, AsyncMock
os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from papermerge.core.features.tags.router import router
from papermerge.core.features.auth import get_current_user
from papermerge.core.db.engine import get_db


def _user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    u.scopes = ["tag:view", "tag:create", "tag:select", "tag:delete", "tag:update"]
    return u


def _db():
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.scalar_one_or_none.return_value = None
    result.scalar.return_value = 0
    db.execute.return_value = result
    _sr = MagicMock()
    _sr.all.return_value = []
    db.scalars.return_value = _sr
    db.scalar.return_value = 0
    return db


app = FastAPI()
app.include_router(router)
app.dependency_overrides[get_current_user] = _user
app.dependency_overrides[get_db] = _db
client = TestClient(app, raise_server_exceptions=False)


def test_list_tags_paginated_returns_empty():
    response = client.get("/tags/")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total_items"] == 0


def test_list_all_tags_returns_empty_list():
    response = client.get("/tags/all")
    assert response.status_code == 200
    assert response.json() == []


def test_get_tag_not_found_returns_404():
    response = client.get(f"/tags/{uuid.uuid4()}")
    assert response.status_code == 404


def test_create_tag_missing_required_fields_returns_422():
    response = client.post("/tags/", json={})
    assert response.status_code == 422


def test_delete_tag_not_found_returns_404():
    response = client.delete(f"/tags/{uuid.uuid4()}")
    assert response.status_code == 404
