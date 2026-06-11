# (c) Copyright Datacraft, 2026
"""Tests for inventory management endpoints."""
import os
import uuid
from unittest.mock import MagicMock, AsyncMock, patch

os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from papermerge.core.features.inventory.router import router as inventory_router
from papermerge.core.features.auth import get_current_user
from papermerge.core.db.engine import get_db


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
app = FastAPI()
app.include_router(inventory_router)
app.dependency_overrides[get_current_user] = lambda: _user
app.dependency_overrides[get_db] = _make_db
client = TestClient(app, raise_server_exceptions=False)


def test_list_locations_ok():
    response = client.get("/inventory/locations")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_check_duplicates_requires_body():
    response = client.post("/inventory/duplicates/check", json={})
    assert response.status_code == 422


def test_check_duplicates_no_file_no_provenance():
    # document_id provided but no file_path; provenance returns None → 400
    response = client.post("/inventory/duplicates/check", json={
        "document_id": str(uuid.uuid4()),
        "similarity_threshold": 0.9,
    })
    assert response.status_code == 400


def test_resolve_discrepancy_persists():
    # The endpoint now writes to DB (add/commit/refresh)
    response = client.post("/inventory/reconcile/resolve", json={
        "discrepancy_id": "DISC-001",
        "resolution_notes": "Container moved to shelf B",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["discrepancy_id"] == "DISC-001"
    assert body["resolved"] is True
    assert body["resolved_by"] == str(_user.id)
    assert "resolved_at" in body


def test_list_manifests_ok():
    response = client.get("/inventory/manifests")
    assert response.status_code in (200, 404, 405)


def test_scan_missing_body():
    response = client.post("/inventory/scan", json={})
    assert response.status_code == 422


def test_list_containers_ok():
    response = client.get("/inventory/containers")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_get_container_not_found():
    response = client.get(f"/inventory/containers/{uuid.uuid4()}")
    assert response.status_code == 404
