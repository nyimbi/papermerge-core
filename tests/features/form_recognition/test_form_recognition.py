import os, uuid
from unittest.mock import MagicMock, AsyncMock
os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from papermerge.core.features.form_recognition.router import router
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
    # db.get() must return None so 404 guards fire correctly
    db.get.return_value = None
    return db


app = FastAPI()
app.include_router(router)
app.dependency_overrides[get_current_user] = _user
app.dependency_overrides[get_db] = _db
client = TestClient(app, raise_server_exceptions=False)


def test_list_templates():
    response = client.get("/forms/templates")
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_get_template_not_found():
    response = client.get(f"/forms/templates/{uuid.uuid4()}")
    assert response.status_code == 404


def test_get_extraction_results():
    response = client.get(f"/forms/extractions/{uuid.uuid4()}")
    assert response.status_code == 404


def test_get_signatures():
    response = client.get(f"/forms/signatures/{uuid.uuid4()}")
    assert response.status_code == 200
    assert response.json()["signatures"] == []
