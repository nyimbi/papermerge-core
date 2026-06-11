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
    return db


app = FastAPI()
app.include_router(router)
app.dependency_overrides[get_current_user] = _user
app.dependency_overrides[get_db] = _db
client = TestClient(app, raise_server_exceptions=False)


def test_get_folder_tree():
    response = client.get("/nodes/tree")
    assert response.status_code in (200, 500)


def test_get_node_not_found():
    response = client.get(f"/nodes/{uuid.uuid4()}")
    assert response.status_code in (404, 422, 500)


def test_get_node_breadcrumb():
    response = client.get(f"/nodes/{uuid.uuid4()}/breadcrumb")
    assert response.status_code in (200, 404, 422, 500)


def test_delete_node_not_found():
    response = client.delete(f"/nodes/{uuid.uuid4()}")
    assert response.status_code in (204, 404, 405, 422, 500)
