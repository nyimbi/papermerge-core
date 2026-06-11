# (c) Copyright Datacraft, 2026
"""Tests for quality management endpoints."""
import os
import uuid
from unittest.mock import MagicMock, AsyncMock

os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from papermerge.core.features.quality.router import router as quality_router
from papermerge.core.features.auth import get_current_user
from papermerge.core.db.engine import get_db

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

def _make_user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = TENANT_ID
    u.username = "testuser"
    u.email = "test@example.com"
    u.is_superuser = False
    u.scopes = ["node:view"]
    return u


def _make_db_session(scalars_result=None, scalar_result=0):
    """Build an AsyncMock session that returns expected query results."""
    db = AsyncMock()
    # scalar() for count queries
    db.scalar.return_value = scalar_result
    # execute() for list queries
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = scalars_result or []
    result_mock.scalar_one_or_none.return_value = None
    db.execute.return_value = result_mock
    return db


_user = _make_user()
_db = _make_db_session()

app = FastAPI()
app.include_router(quality_router)
app.dependency_overrides[get_current_user] = lambda: _user
app.dependency_overrides[get_db] = lambda: _db

client = TestClient(app)


def test_list_quality_rules_empty():
    response = client.get("/quality/rules")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["items"] == []
    assert data["total"] == 0


def test_list_quality_rules_active_only_param():
    response = client.get("/quality/rules?active_only=true")
    assert response.status_code == 200


def test_list_quality_rules_metric_param():
    response = client.get("/quality/rules?metric=completeness")
    assert response.status_code == 200


def test_list_quality_assessments_empty():
    response = client.get("/quality/assessments")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data


def test_quality_rule_not_found():
    # router uses result.scalar(), not scalar_one_or_none()
    _db.execute.return_value.scalar.return_value = None
    rid = str(uuid.uuid4())
    response = client.get(f"/quality/rules/{rid}")
    assert response.status_code == 404
