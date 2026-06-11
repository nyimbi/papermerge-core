# (c) Copyright Datacraft, 2026
"""Tests for audit log integrity and cryptographic chaining."""
import os
import uuid
import pytest
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock

os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from papermerge.core import orm
from papermerge.core.features.audit.security import verify_audit_chain, calculate_audit_hash


def _make_entry(previous_hash: str | None) -> orm.AuditLog:
    entry = MagicMock(spec=orm.AuditLog)
    entry.id = uuid.uuid4()
    entry.timestamp = datetime(2026, 1, 1)
    entry.table_name = "documents"
    entry.record_id = uuid.uuid4()
    entry.operation = "INSERT"
    entry.user_id = uuid.uuid4()
    entry.old_values = None
    entry.new_values = None
    entry.previous_hash = previous_hash
    # Compute the real hash for this entry
    entry.hash = calculate_audit_hash(entry, previous_hash)
    return entry


def _make_session(entries):
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = entries
    session.execute.return_value = result_mock
    return session


@pytest.mark.asyncio
async def test_verify_audit_chain_valid():
    """A properly-chained sequence of entries passes verification."""
    e1 = _make_entry(None)
    e2 = _make_entry(e1.hash)
    e3 = _make_entry(e2.hash)

    session = _make_session([e1, e2, e3])
    success, error = await verify_audit_chain(session)
    assert success is True
    assert error is None


@pytest.mark.asyncio
async def test_verify_audit_chain_broken_link():
    """A broken previous_hash link is detected."""
    e1 = _make_entry(None)
    e2 = _make_entry("wrong_hash")   # wrong — should be e1.hash

    session = _make_session([e1, e2])
    success, error = await verify_audit_chain(session)
    assert success is False
    assert error is not None


@pytest.mark.asyncio
async def test_verify_audit_chain_tampered_hash():
    """A tampered self-hash is detected."""
    e1 = _make_entry(None)
    e2 = _make_entry(e1.hash)
    e2.hash = "tampered"  # override with wrong value

    session = _make_session([e1, e2])
    success, error = await verify_audit_chain(session)
    assert success is False
    assert error is not None


@pytest.mark.asyncio
async def test_verify_audit_chain_empty():
    """An empty log passes (nothing to verify)."""
    session = _make_session([])
    success, error = await verify_audit_chain(session)
    assert success is True
    assert error is None
