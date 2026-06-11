# (c) Copyright Datacraft, 2026
"""Tests for workflow router endpoints — UUID validation and assigned tasks."""
import os
import uuid
from unittest.mock import MagicMock, AsyncMock

os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from papermerge.core.features.workflows.router import router as workflows_router
from papermerge.core.features.auth import get_current_user
from papermerge.core.db.engine import get_db
from papermerge.core.features.workflows.prefect_engine import PrefectWorkflowEngine
from papermerge.core.features.workflows.router import get_workflow_engine

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

def _make_user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = TENANT_ID
    u.username = "testuser"
    u.email = "test@example.com"
    u.is_superuser = False
    u.scopes = ["node:view", "node:update"]
    return u


def _make_db_session(scalars_result=None, scalar_result=0):
    db = AsyncMock()
    db.scalar.return_value = scalar_result
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = scalars_result or []
    result_mock.scalar_one_or_none.return_value = None
    db.execute.return_value = result_mock
    return db


def _make_engine():
    engine = AsyncMock(spec=PrefectWorkflowEngine)
    engine.get_pending_tasks.return_value = []
    return engine


_user = _make_user()
_db = _make_db_session()
_engine = _make_engine()

app = FastAPI()
app.include_router(workflows_router)
app.dependency_overrides[get_current_user] = lambda: _user
app.dependency_overrides[get_db] = lambda: _db
app.dependency_overrides[get_workflow_engine] = lambda: _engine

client = TestClient(app)


def test_list_executions_invalid_uuid_returns_422():
    """Invalid workflow_id UUID should return HTTP 422, not silently drop the filter."""
    response = client.get("/workflows/executions/?workflow_id=not-a-uuid")
    assert response.status_code == 422
    assert "Invalid workflow_id" in response.json()["detail"]


def test_list_executions_valid_uuid_accepted():
    """Valid UUID in workflow_id should be accepted."""
    valid_id = str(uuid.uuid4())
    response = client.get(f"/workflows/executions/?workflow_id={valid_id}")
    assert response.status_code == 200


def test_list_executions_no_filter():
    response = client.get("/workflows/executions/")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data


def test_get_assigned_tasks_empty():
    """get_assigned_tasks should return empty list when no approval requests exist."""
    response = client.get("/workflows/tasks/assigned")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_get_assigned_tasks_status_filter():
    response = client.get("/workflows/tasks/assigned?status=pending")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_get_assigned_tasks_limit_param():
    response = client.get("/workflows/tasks/assigned?limit=10")
    assert response.status_code == 200
