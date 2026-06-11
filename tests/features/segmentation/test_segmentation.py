# (c) Copyright Datacraft, 2026
"""Tests for segmentation endpoints."""
import os
import uuid
from unittest.mock import MagicMock, AsyncMock

os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from papermerge.core.features.segmentation.router import router as segmentation_router
from papermerge.core.features.auth import get_current_user
from papermerge.core.db.engine import get_session


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
app.include_router(segmentation_router)
app.dependency_overrides[get_current_user] = lambda: _user
app.dependency_overrides[get_session] = lambda: _db
client = TestClient(app)


def test_list_segmentation_jobs_ok():
    response = client.get("/segmentation/jobs")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_get_segmentation_job_not_found():
    response = client.get(f"/segmentation/{uuid.uuid4()}")
    assert response.status_code in (404, 422)
