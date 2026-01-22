# (c) Copyright Datacraft, 2026
"""Tests for audit log integrity and cryptographic chaining."""
import pytest
import uuid
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock

from papermerge.core import orm
from papermerge.core.features.audit.security import verify_audit_chain

@pytest.mark.asyncio
async def test_verify_audit_chain_valid():
    """Test that a valid audit chain passes verification."""
    session = AsyncMock()
    
    # Create a valid chain of 3 entries
    h1 = "hash1"
    h2 = "hash2"
    h3 = "hash3"
    
    entries = [
        orm.AuditLog(id=uuid.uuid4(), timestamp=datetime(2026, 1, 1), hash=h1, previous_hash=None),
        orm.AuditLog(id=uuid.uuid4(), timestamp=datetime(2026, 1, 2), hash=h2, previous_hash=h1),
        orm.AuditLog(id=uuid.uuid4(), timestamp=datetime(2026, 1, 3), hash=h3, previous_hash=h2),
    ]
    
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = entries
    session.execute.return_value = result_mock
    
    success, error = await verify_audit_chain(session)
    assert success is True
    assert error is None

@pytest.mark.asyncio
async def test_verify_audit_chain_broken():
    """Test that a broken audit chain fails verification."""
    session = AsyncMock()
    
    # Create a broken chain (entry 2 has wrong previous_hash)
    h1 = "hash1"
    h2 = "hash2"
    
    entries = [
        orm.AuditLog(id=uuid.uuid4(), timestamp=datetime(2026, 1, 1), hash=h1, previous_hash=None),
        orm.AuditLog(id=uuid.uuid4(), timestamp=datetime(2026, 1, 2), hash=h2, previous_hash="wrong_hash"),
    ]
    
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = entries
    session.execute.return_value = result_mock
    
    success, error = await verify_audit_chain(session)
    assert success is False
    assert "Audit chain broken" in error
