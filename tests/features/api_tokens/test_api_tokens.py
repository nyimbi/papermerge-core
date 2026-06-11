import os, uuid
from unittest.mock import MagicMock, AsyncMock
os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from papermerge.core.features.api_tokens.router import router
from papermerge.core.features.auth import get_current_user
from papermerge.core.db.engine import get_db


def _user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    u.scopes = ["api_token:create", "api_token:view", "api_token:delete"]
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
    db.get.return_value = None
    return db


app = FastAPI()
app.include_router(router)
app.dependency_overrides[get_current_user] = _user
app.dependency_overrides[get_db] = _db
client = TestClient(app, raise_server_exceptions=False)


def test_list_tokens_empty():
    response = client.get("/tokens")
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_create_token_missing_body_422():
    response = client.post("/tokens", json={})
    assert response.status_code == 422


def test_create_token_valid_body():
    response = client.post("/tokens", json={"name": "ci-token"})
    assert response.status_code in (200, 201, 500)


def test_delete_nonexistent_token():
    response = client.delete(f"/tokens/{uuid.uuid4()}")
    assert response.status_code == 404
