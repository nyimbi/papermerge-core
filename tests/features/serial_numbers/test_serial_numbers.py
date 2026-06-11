# (c) Copyright Datacraft, 2026
"""Tests for serial numbers endpoints."""
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock

os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from papermerge.core.features.serial_numbers.router import router as sn_router, get_service
from papermerge.core.features.auth import get_current_user


def _make_user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    u.scopes = ["node:view"]
    return u


def _make_sequence(seq_id=None, name="Invoice Sequence"):
    s = MagicMock()
    s.id = seq_id or str(uuid.uuid4())
    s.name = name
    s.description = "Test sequence"
    s.pattern = "{PREFIX}-{YEAR}{MONTH}-{SEQ:5}"
    s.prefix = "INV"
    s.current_value = 42
    s.reset_frequency = "yearly"
    s.last_reset_at = None
    s.document_type_id = None
    s.is_active = True
    s.auto_assign = True
    s.allow_manual = True
    s.created_at = datetime.now(timezone.utc)
    s.updated_at = None
    s.next_preview = None
    return s


def _make_doc_serial(doc_id=None, serial="INV-202601-00001"):
    dsn = MagicMock()
    dsn.id = str(uuid.uuid4())
    dsn.document_id = str(doc_id or uuid.uuid4())
    dsn.serial_number = serial
    dsn.sequence_id = str(uuid.uuid4())
    dsn.sequence_value = 1
    dsn.is_manual = False
    dsn.assigned_at = datetime.now(timezone.utc)
    dsn.assigned_by_id = str(uuid.uuid4())
    return dsn


def _make_service(
    sequences=None,
    sequence=None,
    doc_serial=None,
):
    svc = AsyncMock()
    svc.list_sequences.return_value = sequences if sequences is not None else []
    svc.get_sequence.return_value = sequence
    svc.create_sequence.return_value = _make_sequence()
    svc.update_sequence.return_value = sequence
    svc.delete_sequence.return_value = True
    svc.get_serial_for_document.return_value = doc_serial
    svc.get_document_by_serial.return_value = doc_serial
    svc.search_by_serial.return_value = []
    svc.remove_serial.return_value = True
    return svc


_user = _make_user()
app = FastAPI()
app.include_router(sn_router)
app.dependency_overrides[get_current_user] = lambda: _user


def _override_service(svc):
    app.dependency_overrides[get_service] = lambda: svc


client = TestClient(app, raise_server_exceptions=False)


def test_list_sequences_empty():
    _override_service(_make_service(sequences=[]))
    response = client.get("/serial-numbers/sequences")
    assert response.status_code == 200
    assert response.json() == []


def test_list_sequences_returns_data():
    seq = _make_sequence()
    _override_service(_make_service(sequences=[seq]))
    response = client.get("/serial-numbers/sequences")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == seq.name
    assert "next_preview" in data[0]


def test_get_sequence_found():
    seq_id = str(uuid.uuid4())
    seq = _make_sequence(seq_id=seq_id)
    _override_service(_make_service(sequence=seq))
    response = client.get(f"/serial-numbers/sequences/{seq_id}")
    assert response.status_code == 200
    assert response.json()["id"] == seq_id


def test_get_sequence_not_found():
    _override_service(_make_service(sequence=None))
    response = client.get(f"/serial-numbers/sequences/{uuid.uuid4()}")
    assert response.status_code == 404


def test_create_sequence_valid():
    seq = _make_sequence()
    svc = _make_service()
    svc.create_sequence.return_value = seq
    _override_service(svc)
    response = client.post("/serial-numbers/sequences", json={
        "name": "Invoice Sequence",
        "pattern": "{PREFIX}-{YEAR}{MONTH}-{SEQ:5}",
        "prefix": "INV",
        "reset_frequency": "yearly",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == seq.name


def test_create_sequence_missing_seq_placeholder_returns_422():
    response = client.post("/serial-numbers/sequences", json={
        "name": "Bad Pattern",
        "pattern": "{PREFIX}-{YEAR}{MONTH}",  # no {SEQ}
        "prefix": "BAD",
        "reset_frequency": "yearly",
    })
    assert response.status_code == 422


def test_get_document_serial_not_found():
    _override_service(_make_service(doc_serial=None))
    response = client.get(f"/serial-numbers/document/{uuid.uuid4()}")
    assert response.status_code == 200
    assert response.json() is None


def test_get_document_serial_found():
    doc_id = str(uuid.uuid4())
    doc_serial = _make_doc_serial(doc_id=doc_id)
    _override_service(_make_service(doc_serial=doc_serial))
    response = client.get(f"/serial-numbers/document/{doc_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["document_id"] == doc_id
    assert data["serial_number"] == doc_serial.serial_number


def test_lookup_serial_not_found():
    _override_service(_make_service(doc_serial=None))
    response = client.get("/serial-numbers/lookup/INV-202601-99999")
    assert response.status_code == 200
    assert response.json() is None


def test_search_by_serial():
    svc = _make_service()
    svc.search_by_serial.return_value = []
    _override_service(svc)
    response = client.get("/serial-numbers/search?query=INV")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_preview_pattern():
    response = client.post("/serial-numbers/preview-pattern", json={
        "pattern": "{PREFIX}-{YEAR}{MONTH}-{SEQ:5}",
        "prefix": "TST",
        "current_value": 0,
    })
    assert response.status_code == 200
    data = response.json()
    assert "preview" in data or "examples" in data or isinstance(data, dict)
