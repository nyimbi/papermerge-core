# (c) Copyright Datacraft, 2026
"""Tests for monitoring endpoints."""
import os

os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

import pytest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from papermerge.core.features.monitoring.router import router as monitoring_router

# Minimal app with just the monitoring router — avoids full app import
app = FastAPI()
app.include_router(monitoring_router)
client = TestClient(app)


@patch("papermerge.core.features.monitoring.router.check_db_status")
@patch("papermerge.core.features.monitoring.router.check_redis_status")
def test_health_check_ok(mock_redis, mock_db):
    mock_db.return_value = True
    mock_redis.return_value = True

    response = client.get("/monitoring/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "details": {
            "database": "up",
            "redis": "up",
        },
    }


@patch("papermerge.core.features.monitoring.router.check_db_status")
@patch("papermerge.core.features.monitoring.router.check_redis_status")
def test_health_check_fail(mock_redis, mock_db):
    mock_db.return_value = False
    mock_redis.return_value = True

    response = client.get("/monitoring/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert data["details"]["database"] == "down"


def test_metrics_endpoint():
    response = client.get("/monitoring/metrics")
    assert response.status_code == 200
    # python_gc_objects_collected_total is always present (cross-platform)
    assert "python_gc_objects_collected_total" in response.text
