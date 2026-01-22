import sys
from unittest.mock import MagicMock, patch

# Mock email_validator module BEFORE any other imports
sys.modules["email_validator"] = MagicMock()

import pytest
import importlib.metadata

# Patch version to avoid PackageNotFoundError
with patch("importlib.metadata.version", return_value="3.6.0"):
    from papermerge.app import app

from fastapi.testclient import TestClient

client = TestClient(app)

@patch("papermerge.core.features.monitoring.router.check_db_status")
@patch("papermerge.core.features.monitoring.router.check_redis_status")
def test_health_check_ok(mock_redis, mock_db):
    mock_db.return_value = True
    mock_redis.return_value = True

    # Assuming default config with empty prefix
    response = client.get("/monitoring/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "details": {
            "database": "up",
            "redis": "up"
        }
    }

@patch("papermerge.core.features.monitoring.router.check_db_status")
@patch("papermerge.core.features.monitoring.router.check_redis_status")
def test_health_check_fail(mock_redis, mock_db):
    mock_db.return_value = False
    mock_redis.return_value = True

    response = client.get("/monitoring/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "error",
        "details": {
            "database": "down",
            "redis": "up"
        }
    }

def test_metrics_endpoint():
    response = client.get("/monitoring/metrics")
    assert response.status_code == 200
    assert "process_cpu_seconds_total" in response.text
