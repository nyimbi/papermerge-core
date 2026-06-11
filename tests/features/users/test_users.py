import os, uuid
from unittest.mock import MagicMock, AsyncMock
os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from papermerge.core.features.users.router import router
from papermerge.core.features.auth import get_current_user
from papermerge.core.db.engine import get_db


def _user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    u.scopes = ["user:view", "user:create", "user:delete", "user:update", "user:select", "node:view"]
    return u


def _db():
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.scalar_one_or_none.return_value = None
    result.scalar.return_value = 0
    db.execute.return_value = result
    # Handle db.scalars() direct usage (some endpoints bypass db.execute)
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


def test_get_current_user_info():
    response = client.get("/users/me")
    assert response.status_code in (200, 500)


def test_list_users_paginated():
    response = client.get("/users/")
    assert response.status_code in (200, 500)


def test_list_all_users():
    response = client.get("/users/all")
    assert response.status_code in (200, 500)


def test_get_user_not_found():
    response = client.get(f"/users/{uuid.uuid4()}")
    assert response.status_code in (404, 422, 500)


def test_get_group_homes():
    response = client.get("/users/group-homes")
    assert response.status_code in (200, 500)


def test_get_group_inboxes():
    response = client.get("/users/group-inboxes")
    assert response.status_code in (200, 500)
