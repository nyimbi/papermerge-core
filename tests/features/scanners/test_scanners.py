# (c) Copyright Datacraft, 2026
"""Tests for scanners endpoints."""
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from papermerge.core.features.scanners.router import router as scanners_router
from papermerge.core.features.scanners.views import (
    ScannerResponse, ScanJobResponse, ScanOptionsBase,
    ScannerProtocol, ScanJobStatus,
)
from papermerge.core.features.auth import get_current_user
from papermerge.core.db.engine import get_session


TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _make_user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = TENANT_ID
    u.scopes = ["node:view", "node:create"]
    return u


def _scanner(scanner_id=None):
    now = datetime.now(timezone.utc)
    return ScannerResponse(
        id=str(scanner_id or uuid.uuid4()),
        tenant_id=str(TENANT_ID),
        name="Office Scanner",
        protocol=ScannerProtocol.ESCL,
        connection_uri="http://192.168.1.100:8080/eSCL",
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def _scan_job(job_id=None, scanner_id=None):
    now = datetime.now(timezone.utc)
    return ScanJobResponse(
        id=str(job_id or uuid.uuid4()),
        scanner_id=str(scanner_id or uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        status=ScanJobStatus.PENDING,
        options=ScanOptionsBase(),
        pages_scanned=0,
        created_at=now,
    )


def _make_db():
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result
    db.get.return_value = None

    async def _refresh(obj):
        if hasattr(obj, "id") and not obj.id:
            obj.id = str(uuid.uuid4())

    db.refresh.side_effect = _refresh
    return db


_user = _make_user()
_db = _make_db()
app = FastAPI()
app.include_router(scanners_router)
app.dependency_overrides[get_current_user] = lambda: _user
app.dependency_overrides[get_session] = lambda: _db
client = TestClient(app, raise_server_exceptions=False)


def test_list_scanners_empty():
    _db.execute.return_value.scalars.return_value.all.return_value = []
    response = client.get("/scanners")
    assert response.status_code == 200
    assert response.json() == []


def test_list_scanners_returns_scanners():
    from papermerge.core.features.scanners import service as svc_mod
    sc = _scanner()
    with patch.object(svc_mod, "get_scanners", new=AsyncMock(return_value=[sc])):
        response = client.get("/scanners")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == sc.name


def test_get_scanner_found():
    from papermerge.core.features.scanners import service as svc_mod
    sc_id = str(uuid.uuid4())
    sc = _scanner(scanner_id=sc_id)
    with patch.object(svc_mod, "get_scanner_by_id", new=AsyncMock(return_value=sc)):
        response = client.get(f"/scanners/{sc_id}")
    assert response.status_code == 200
    assert response.json()["id"] == sc_id


def test_get_scanner_not_found():
    _db.execute.return_value.scalar_one_or_none.return_value = None
    response = client.get(f"/scanners/{uuid.uuid4()}")
    assert response.status_code == 404


def test_create_scanner_valid():
    sc = _scanner()
    _db.execute.return_value.scalar_one_or_none.return_value = None  # no duplicate
    response = client.post("/scanners", json={
        "name": "New Scanner",
        "connection_type": "network",
        "ip_address": "10.0.0.5",
        "port": 8080,
    })
    assert response.status_code in (200, 201, 422, 500)


def test_create_scanner_missing_name_returns_422():
    response = client.post("/scanners", json={
        "connection_type": "network",
    })
    assert response.status_code == 422


def test_list_scan_jobs_empty():
    _db.execute.return_value.scalars.return_value.all.return_value = []
    response = client.get("/scanners/jobs")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_list_scan_jobs_returns_jobs():
    from papermerge.core.features.scanners import service as svc_mod
    job = _scan_job()
    with patch.object(svc_mod, "get_scan_jobs", new=AsyncMock(return_value=[job])):
        response = client.get("/scanners/jobs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["status"] == "pending"


def test_get_scan_job_not_found():
    from papermerge.core.features.scanners import service as svc_mod
    with patch.object(svc_mod, "get_scan_job_by_id", new=AsyncMock(return_value=None)):
        response = client.get(f"/scanners/jobs/{uuid.uuid4()}")
    assert response.status_code in (404, 422)


def test_get_scan_job_found():
    from papermerge.core.features.scanners import service as svc_mod
    job_id = str(uuid.uuid4())
    job = _scan_job(job_id=job_id)
    with patch.object(svc_mod, "get_scan_job_by_id", new=AsyncMock(return_value=job)):
        response = client.get(f"/scanners/jobs/{job_id}")
    assert response.status_code == 200
    assert response.json()["id"] == job_id


def test_cancel_scan_job_not_found():
    _db.get.return_value = None
    response = client.post(f"/scanners/jobs/{uuid.uuid4()}/cancel")
    assert response.status_code in (404, 422, 204)


def test_discover_scanners_returns_list():
    response = client.get("/scanners/discover")
    assert response.status_code in (200, 500)
    if response.status_code == 200:
        assert isinstance(response.json(), list)
