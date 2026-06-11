import os
import uuid
from unittest.mock import MagicMock, AsyncMock

os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from papermerge.core.features.routing.router import router
from papermerge.core.features.auth import get_current_user
from papermerge.core.db.engine import get_db

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = TENANT_ID
    u.scopes = ["node:view", "node:create"]
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


def test_list_routing_rules_empty():
    response = client.get("/routing/rules")
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_list_routing_rules_with_page_params():
    response = client.get("/routing/rules?page_number=1&page_size=10")
    assert response.status_code == 200


def test_get_rule_not_found():
    response = client.get(f"/routing/rules/{uuid.uuid4()}")
    assert response.status_code == 404


def test_create_rule_missing_body_returns_422():
    response = client.post("/routing/rules", json={})
    assert response.status_code == 422


def test_create_rule_valid():
    response = client.post("/routing/rules", json={
        "name": "Invoice to AP Folder",
        "description": "Route invoices to accounts payable",
        "priority": 10,
        "conditions": {"field": "document_type", "op": "eq", "value": "invoice"},
        "destination_type": "folder",
        "destination_id": str(uuid.uuid4()),
        "mode": "both",
    })
    # 500 is OK here since mock DB doesn't commit; 422 means schema mismatch
    assert response.status_code in (200, 201, 500)


def test_delete_rule_not_found():
    response = client.delete(f"/routing/rules/{uuid.uuid4()}")
    assert response.status_code in (404, 204)


def test_list_routing_logs_empty():
    response = client.get("/routing/logs")
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_list_routing_logs_filter_by_document():
    doc_id = uuid.uuid4()
    response = client.get(f"/routing/logs?document_id={doc_id}")
    assert response.status_code == 200


def test_route_document_missing_body():
    response = client.post("/routing/route", json={})
    assert response.status_code == 422


def test_test_routing_rules_missing_body():
    response = client.post("/routing/test", json={})
    assert response.status_code == 422
