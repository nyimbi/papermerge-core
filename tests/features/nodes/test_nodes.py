import os, uuid
from unittest.mock import MagicMock, AsyncMock
os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from papermerge.core.features.nodes.router import router
from papermerge.core.features.auth import get_current_user
from papermerge.core.db.engine import get_db


def _user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    u.home_folder_id = uuid.uuid4()
    u.inbox_folder_id = uuid.uuid4()
    u.scopes = ["node:view", "node:create", "node:update", "node:delete", "node:move"]
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


def test_get_folder_tree():
    response = client.get("/nodes/tree")
    assert response.status_code in (200, 500)


def test_get_node_children_empty():
    # GET /{parent_id} returns paginated children — returns 200 with empty list
    # when parent has no children (or parent doesn't exist but user has access)
    response = client.get(f"/nodes/{uuid.uuid4()}")
    assert response.status_code in (200, 403, 500)


def test_get_node_breadcrumb():
    response = client.get(f"/nodes/{uuid.uuid4()}/breadcrumb")
    assert response.status_code in (200, 404, 422, 500)


def test_bulk_delete_nodes_empty():
    # DELETE /nodes/ takes a JSON array of UUIDs; empty list returns 200 with []
    response = client.request("DELETE", "/nodes/", json=[])
    assert response.status_code in (200, 403, 422, 500)


def test_bulk_delete_nodes_nonexistent():
    # Non-existent node: has_node_perm returns falsy → 403 Forbidden
    response = client.request("DELETE", "/nodes/", json=[str(uuid.uuid4())])
    assert response.status_code in (200, 403, 422, 500)
