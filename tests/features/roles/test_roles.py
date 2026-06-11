import os, uuid
from unittest.mock import MagicMock, AsyncMock
from sqlalchemy.exc import NoResultFound
os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from papermerge.core.features.roles.router import router
from papermerge.core.features.auth import get_current_user
from papermerge.core.db.engine import get_db


def _user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    u.scopes = ["role:view", "role:create", "role:delete"]
    return u


def _db():
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.scalar_one_or_none.return_value = None
    result.scalar.return_value = 0
    # result.one() raises NoResultFound so GET /{id} returns 404 correctly
    result.one.side_effect = NoResultFound()
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


def test_list_roles_returns_empty_paginated():
    response = client.get("/roles/")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total_items"] == 0


def test_list_all_roles_returns_empty_list():
    response = client.get("/roles/all")
    assert response.status_code == 200
    assert response.json() == []


def test_get_role_not_found_returns_404():
    response = client.get(f"/roles/{uuid.uuid4()}")
    assert response.status_code == 404


def test_create_role_missing_body_returns_422():
    response = client.post("/roles/", json={})
    assert response.status_code == 422


def test_delete_role_returns_204():
    response = client.delete(f"/roles/{uuid.uuid4()}")
    assert response.status_code == 204
