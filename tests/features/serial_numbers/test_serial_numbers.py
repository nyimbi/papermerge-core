# (c) Copyright Datacraft, 2026
"""Tests for serial numbers endpoints."""
import os
import uuid
from unittest.mock import MagicMock, AsyncMock

os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from papermerge.core.features.serial_numbers.router import router as sn_router
from papermerge.core.features.auth import get_current_user
from papermerge.core.db.engine import get_db


def _make_user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    u.scopes = ["node:view"]
    return u


def _make_db():
    db = AsyncMock()
    db.scalar.return_value = 0
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    result_mock.scalar_one_or_none.return_value = None
    result_mock.scalar.return_value = None
    db.execute.return_value = result_mock
    return db


_user = _make_user()
_db = _make_db()
app = FastAPI()
app.include_router(sn_router)
app.dependency_overrides[get_current_user] = lambda: _user
app.dependency_overrides[get_db] = lambda: _db
client = TestClient(app)


def test_list_sequences_empty():
    response = client.get("/serial-numbers/sequences")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_get_sequence_not_found():
    response = client.get(f"/serial-numbers/sequences/{uuid.uuid4()}")
    assert response.status_code == 404


def test_assign_serial_document_not_found():
    response = client.post(f"/serial-numbers/assign/{uuid.uuid4()}")
    assert response.status_code in (404, 422, 400)
