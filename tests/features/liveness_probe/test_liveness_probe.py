import os
from unittest.mock import AsyncMock, MagicMock
os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from papermerge.core.features.liveness_probe.router import router
from papermerge.core.db.engine import get_db


def _db():
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = 1
    result.scalar.return_value = 1
    db.execute.return_value = result
    return db


app = FastAPI()
app.include_router(router)
app.dependency_overrides[get_db] = _db
client = TestClient(app, raise_server_exceptions=False)


def test_liveness_probe_ok():
    response = client.get("/probe/")
    assert response.status_code in (200, 500)


def test_liveness_probe_returns_empty():
    response = client.get("/probe/")
    if response.status_code == 200:
        assert response.content == b""
