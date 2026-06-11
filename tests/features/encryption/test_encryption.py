import os, uuid
from unittest.mock import MagicMock, AsyncMock
os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from papermerge.core.features.encryption.router import router
from papermerge.core.features.auth import get_current_user
from papermerge.core.db.engine import get_db


def _user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    u.scopes = []
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


def test_list_encryption_keys():
    response = client.get("/encryption/keys")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body


def test_get_key_not_found():
    response = client.get(f"/encryption/keys/{uuid.uuid4()}")
    assert response.status_code in (404, 422)


def test_list_access_requests():
    response = client.get("/encryption/hidden-access/pending")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body


def test_request_single_view_missing_body():
    response = client.post("/encryption/single-view", json={})
    assert response.status_code == 422
