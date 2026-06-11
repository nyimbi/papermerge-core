# (c) Copyright Datacraft, 2026
"""Tests for departments API endpoints."""
import os
import uuid
from unittest.mock import MagicMock, AsyncMock, patch

os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from papermerge.core.features.departments.router import router as departments_router
from papermerge.core.features.departments.schema import Department as DeptSchema
from papermerge.core.features.auth import get_current_user
from papermerge.core.db.engine import get_session as get_async_session

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _make_user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = TENANT_ID
    u.username = "testuser"
    u.email = "test@example.com"
    u.is_superuser = False
    u.scopes = ["node:view", "node:create"]
    return u


def _make_db_session():
    db = AsyncMock()
    db.scalar.return_value = 0
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    result_mock.scalar_one_or_none.return_value = None
    db.execute.return_value = result_mock
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=False)
    return db


_user = _make_user()
_db = _make_db_session()

app = FastAPI()
app.include_router(departments_router)
app.dependency_overrides[get_current_user] = lambda: _user
app.dependency_overrides[get_async_session] = lambda: _db

client = TestClient(app, raise_server_exceptions=False)


def test_list_departments_empty():
    with patch(
        "papermerge.core.features.departments.db.api.list_departments",
        new=AsyncMock(return_value=([], 0)),
    ):
        response = client.get("/departments")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["items"] == []
    assert data["total"] == 0


def test_list_departments_pagination_params():
    with patch(
        "papermerge.core.features.departments.db.api.list_departments",
        new=AsyncMock(return_value=([], 0)),
    ):
        response = client.get("/departments?page_size=5&page_number=2")
    assert response.status_code == 200


def test_list_departments_with_results():
    dept = DeptSchema(id=uuid.uuid4(), name="Engineering", parent_id=None)
    with patch(
        "papermerge.core.features.departments.db.api.list_departments",
        new=AsyncMock(return_value=([dept], 1)),
    ):
        response = client.get("/departments")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["name"] == "Engineering"


def test_get_department_not_found():
    with patch(
        "papermerge.core.features.departments.db.api.get_department",
        new=AsyncMock(return_value=None),
    ):
        response = client.get(f"/departments/{uuid.uuid4()}")
    assert response.status_code == 404


def test_department_tree_empty():
    with patch(
        "papermerge.core.features.departments.db.api.get_department_tree",
        new=AsyncMock(return_value=[]),
    ):
        response = client.get("/departments/tree")
    assert response.status_code == 200
    assert response.json() == []


def test_create_department_missing_name_returns_422():
    response = client.post("/departments", json={})
    assert response.status_code == 422


def test_create_department_valid():
    new_dept = DeptSchema(id=uuid.uuid4(), name="Finance", parent_id=None)
    with patch(
        "papermerge.core.features.departments.db.api.create_department",
        new=AsyncMock(return_value=new_dept),
    ):
        response = client.post("/departments", json={"name": "Finance"})
    assert response.status_code in (200, 201)


def test_list_department_members_empty():
    mock_dept = MagicMock(id=uuid.uuid4(), tenant_id=TENANT_ID)
    mock_dept.members = []
    with patch(
        "papermerge.core.features.departments.db.api.get_department",
        new=AsyncMock(return_value=mock_dept),
    ):
        response = client.get(f"/departments/{uuid.uuid4()}/members")
    assert response.status_code == 200
    assert response.json() == []


def test_delete_department_not_found():
    with patch(
        "papermerge.core.features.departments.db.api.get_department",
        new=AsyncMock(return_value=None),
    ):
        response = client.delete(f"/departments/{uuid.uuid4()}")
    assert response.status_code in (204, 404)
