# (c) Copyright Datacraft, 2026
"""Tests for segmentation endpoints."""
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

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

    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.scalar_one_or_none.return_value = None
    result.scalar.return_value = 0
    db.execute.return_value = result

    async def _refresh(obj):
        if hasattr(obj, "id") and not obj.id:
            obj.id = str(uuid.uuid4())

    db.refresh.side_effect = _refresh
    return db


def _make_job(job_id=None, status="pending"):
    job = MagicMock()
    job.id = job_id or str(uuid.uuid4())
    job.source_document_id = str(uuid.uuid4())
    job.source_page_number = None
    job.method = "hybrid"
    job.auto_create_documents = False
    job.min_confidence_threshold = 0.8
    job.status = status
    job.documents_detected = 0
    job.segments_created = 0
    job.processing_time_ms = None
    job.error_message = None
    job.celery_task_id = None
    job.initiated_by_id = uuid.uuid4()
    job.tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    job.created_at = datetime.now(timezone.utc)
    job.started_at = None
    job.completed_at = None
    return job


_user = _make_user()
_db = _make_db()
app = FastAPI()
app.include_router(segmentation_router)
app.dependency_overrides[get_current_user] = lambda: _user
app.dependency_overrides[get_session] = lambda: _db
client = TestClient(app, raise_server_exceptions=False)


def test_list_segmentation_jobs_empty():
    _db.execute.return_value.scalars.return_value.all.return_value = []
    response = client.get("/segmentation/jobs")
    assert response.status_code == 200
    assert response.json() == []


def test_list_segmentation_jobs_returns_jobs():
    job = _make_job(status="completed")
    _db.execute.return_value.scalars.return_value.all.return_value = [job]
    response = client.get("/segmentation/jobs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == job.id
    assert data[0]["status"] == "completed"
    _db.execute.return_value.scalars.return_value.all.return_value = []


def test_get_segmentation_job_found():
    job_id = str(uuid.uuid4())
    job = _make_job(job_id=job_id, status="processing")
    _db.execute.return_value.scalar_one_or_none.return_value = job
    response = client.get(f"/segmentation/jobs/{job_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == job_id
    assert data["status"] == "processing"
    _db.execute.return_value.scalar_one_or_none.return_value = None


def test_get_segmentation_job_not_found():
    _db.execute.return_value.scalar_one_or_none.return_value = None
    response = client.get(f"/segmentation/jobs/{uuid.uuid4()}")
    assert response.status_code == 404


def test_start_segmentation_dispatches_task():
    with patch("papermerge.core.features.segmentation.router.celery_app") as mock_celery:
        mock_celery.send_task.return_value = MagicMock(id="celery-task-123")
        response = client.post("/segmentation/analyze", json={
            "document_id": str(uuid.uuid4()),
            "method": "hybrid",
            "min_confidence": 0.8,
            "auto_create_documents": False,
        })
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "processing"
    assert data["celery_task_id"] == "celery-task-123"
    assert "job_id" in data


def test_start_segmentation_celery_failure_returns_500():
    with patch("papermerge.core.features.segmentation.router.celery_app") as mock_celery:
        mock_celery.send_task.side_effect = ConnectionError("broker unavailable")
        response = client.post("/segmentation/analyze", json={
            "document_id": str(uuid.uuid4()),
            "method": "hybrid",
            "min_confidence": 0.7,
        })
    assert response.status_code == 500


def test_start_segmentation_invalid_method_returns_422():
    response = client.post("/segmentation/analyze", json={
        "document_id": str(uuid.uuid4()),
        "method": "nonexistent_method",
    })
    assert response.status_code == 422


def test_list_segments_empty():
    _db.execute.return_value.scalars.return_value.all.return_value = []
    _db.execute.return_value.scalar.return_value = 0
    response = client.get("/segmentation/segments")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["items"] == []


def test_list_jobs_with_limit_param():
    _db.execute.return_value.scalars.return_value.all.return_value = []
    response = client.get("/segmentation/jobs?limit=10")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
