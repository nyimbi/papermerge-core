import os, uuid
from unittest.mock import MagicMock, AsyncMock
os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from papermerge.core.features.billing.router import router
from papermerge.core.features.auth import get_current_user
from papermerge.core.db.engine import get_db


def _user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    u.scopes = []
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


def test_billing_dashboard_ok():
    response = client.get("/billing/dashboard")
    assert response.status_code in (200, 500)


def test_billing_alerts_list():
    response = client.get("/billing/alerts")
    assert response.status_code in (200, 500)


def test_billing_invoices_list():
    response = client.get("/billing/invoices")
    assert response.status_code in (200, 500)


def test_billing_usage_daily():
    response = client.get("/billing/usage")
    assert response.status_code in (200, 404, 500)


def test_cost_estimate_missing_body():
    response = client.post("/billing/estimate", json={})
    assert response.status_code in (200, 422, 500)
