import os
import uuid
from unittest.mock import MagicMock, AsyncMock, patch

os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from papermerge.core.features.search.router import router
from papermerge.core.features.auth import get_current_user
from papermerge.core import db as core_db
from papermerge.core.features.search.schema import SearchDocumentsResponse


def _user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    u.scopes = ["node:view"]
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


_EMPTY_RESPONSE = SearchDocumentsResponse(
    items=[],
    page_number=1,
    page_size=20,
    total_items=0,
    num_pages=0,
    custom_fields=[],
    document_type_id=None,
)

app = FastAPI()
app.include_router(router)
app.dependency_overrides[get_current_user] = _user
app.dependency_overrides[core_db.get_db] = _db
client = TestClient(app, raise_server_exceptions=False)


def test_search_no_filters_returns_empty():
    with patch.object(core_db, "search_documents", new=AsyncMock(return_value=_EMPTY_RESPONSE)):
        response = client.post("/search/", json={})
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total_items"] == 0


def test_search_with_fts_query():
    with patch.object(core_db, "search_documents", new=AsyncMock(return_value=_EMPTY_RESPONSE)):
        response = client.post("/search/", json={
            "filters": {"fts": {"terms": ["invoice 2024"]}},
        })
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_search_pagination_params_accepted():
    with patch.object(core_db, "search_documents", new=AsyncMock(return_value=_EMPTY_RESPONSE)):
        response = client.post("/search/", json={
            "page_number": 2,
            "page_size": 10,
        })
    assert response.status_code == 200


def test_search_sort_by_accepted():
    custom_response = SearchDocumentsResponse(
        items=[], page_number=1, page_size=20, total_items=0, num_pages=0,
        custom_fields=[], document_type_id=None,
    )
    with patch.object(core_db, "search_documents", new=AsyncMock(return_value=custom_response)):
        response = client.post("/search/", json={
            "sort_by": "title",
            "sort_direction": "asc",
        })
    assert response.status_code == 200


def test_search_response_has_required_fields():
    with patch.object(core_db, "search_documents", new=AsyncMock(return_value=_EMPTY_RESPONSE)):
        response = client.post("/search/", json={})
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total_items" in data
    assert "page_number" in data
    assert "page_size" in data


def test_search_raises_value_error_returns_400():
    with patch.object(core_db, "search_documents", new=AsyncMock(side_effect=ValueError("invalid date range"))):
        response = client.post("/search/", json={"filters": {}})
    assert response.status_code == 400


def test_search_internal_error_returns_500():
    with patch.object(core_db, "search_documents", new=AsyncMock(side_effect=RuntimeError("db error"))):
        response = client.post("/search/", json={})
    assert response.status_code == 500


def test_search_with_tag_filter():
    with patch.object(core_db, "search_documents", new=AsyncMock(return_value=_EMPTY_RESPONSE)):
        response = client.post("/search/", json={
            "filters": {"tags": [{"values": ["urgent"]}]},
        })
    assert response.status_code == 200
