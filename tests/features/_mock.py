"""Shared mock helpers for feature tests."""
import uuid
from unittest.mock import AsyncMock, MagicMock


def make_db_mock():
    """
    Return an AsyncMock DB session that handles both db.execute() and
    db.scalars() patterns used across different router implementations.
    """
    db = AsyncMock()

    # For db.execute() → result.scalars().all(), scalar_one_or_none(), scalar()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.scalar_one_or_none.return_value = None
    result.scalar.return_value = 0
    db.execute.return_value = result

    # For db.scalars() used directly (e.g. tags/db/api.py)
    scalars_result = MagicMock()
    scalars_result.all.return_value = []
    db.scalars.return_value = scalars_result

    # For db.scalar() used directly
    db.scalar.return_value = 0

    return db


def make_user_mock(
    scopes: list[str] | None = None,
    tenant_id: str = "00000000-0000-0000-0000-000000000001",
):
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.UUID(tenant_id)
    u.home_folder_id = uuid.uuid4()
    u.inbox_folder_id = uuid.uuid4()
    u.scopes = scopes or []
    return u
