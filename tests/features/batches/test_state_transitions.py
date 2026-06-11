# (c) Copyright Datacraft, 2026
"""Tests for ScanBatch state transition business rules.

These test the guards in the router directly, using simple ORM objects
and mocked DB sessions — no real database required.
"""
import os
import uuid
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from fastapi import HTTPException
from papermerge.core.features.batches.db.orm import BatchStatus


def _make_batch(status: BatchStatus):
    """Return a MagicMock that behaves like a ScanBatch ORM row."""
    batch = MagicMock()
    batch.id = str(uuid.uuid4())
    batch.status = status
    batch.tenant_id = uuid.uuid4()
    batch.updated_at = datetime.utcnow()
    batch.completed_at = None
    return batch


def _make_db(batch):
    """Return a mock async DB session that returns `batch` on execute()."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = batch
    db.execute.return_value = result
    return db


# ── complete_batch ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_complete_batch_from_in_progress_succeeds():
    from papermerge.core.features.batches.router import complete_batch
    batch = _make_batch(BatchStatus.IN_PROGRESS)
    db = _make_db(batch)
    user = MagicMock()

    result = await complete_batch(batch.id, db, user)
    assert result.status == BatchStatus.COMPLETED


@pytest.mark.asyncio
async def test_complete_batch_from_created_raises_400():
    from papermerge.core.features.batches.router import complete_batch
    batch = _make_batch(BatchStatus.CREATED)
    db = _make_db(batch)
    user = MagicMock()

    with pytest.raises(HTTPException) as exc:
        await complete_batch(batch.id, db, user)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_complete_batch_not_found_raises_404():
    from papermerge.core.features.batches.router import complete_batch
    db = _make_db(None)
    user = MagicMock()

    with pytest.raises(HTTPException) as exc:
        await complete_batch("nonexistent", db, user)
    assert exc.value.status_code == 404


# ── cancel_batch ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_batch_from_created_succeeds():
    from papermerge.core.features.batches.router import cancel_batch
    batch = _make_batch(BatchStatus.CREATED)
    db = _make_db(batch)
    user = MagicMock()

    result = await cancel_batch(batch.id, db, user)
    assert result.status == BatchStatus.CANCELLED


@pytest.mark.asyncio
async def test_cancel_already_cancelled_raises_400():
    from papermerge.core.features.batches.router import cancel_batch
    batch = _make_batch(BatchStatus.CANCELLED)
    db = _make_db(batch)
    user = MagicMock()

    with pytest.raises(HTTPException) as exc:
        await cancel_batch(batch.id, db, user)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_cancel_completed_batch_raises_400():
    from papermerge.core.features.batches.router import cancel_batch
    batch = _make_batch(BatchStatus.COMPLETED)
    db = _make_db(batch)
    user = MagicMock()

    with pytest.raises(HTTPException) as exc:
        await cancel_batch(batch.id, db, user)
    assert exc.value.status_code == 400


# ── review_batch ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_review_batch_from_completed_succeeds():
    from papermerge.core.features.batches.router import review_batch
    batch = _make_batch(BatchStatus.COMPLETED)
    db = _make_db(batch)
    user = MagicMock()

    result = await review_batch(batch.id, db, user)
    assert result.status == BatchStatus.UNDER_REVIEW


@pytest.mark.asyncio
async def test_review_batch_from_created_raises_400():
    from papermerge.core.features.batches.router import review_batch
    batch = _make_batch(BatchStatus.CREATED)
    db = _make_db(batch)
    user = MagicMock()

    with pytest.raises(HTTPException) as exc:
        await review_batch(batch.id, db, user)
    assert exc.value.status_code == 400


# ── fail_batch ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fail_batch_from_in_progress_succeeds():
    from papermerge.core.features.batches.router import fail_batch
    batch = _make_batch(BatchStatus.IN_PROGRESS)
    db = _make_db(batch)
    user = MagicMock()

    result = await fail_batch(batch.id, db, user)
    assert result.status == BatchStatus.FAILED


@pytest.mark.asyncio
async def test_fail_already_failed_raises_400():
    from papermerge.core.features.batches.router import fail_batch
    batch = _make_batch(BatchStatus.FAILED)
    db = _make_db(batch)
    user = MagicMock()

    with pytest.raises(HTTPException) as exc:
        await fail_batch(batch.id, db, user)
    assert exc.value.status_code == 400
