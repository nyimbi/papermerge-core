# (c) Copyright Datacraft, 2026
"""Authentication for scanner devices using API keys."""
import secrets
import hashlib
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from .models import ScannerModel

API_KEY_NAME = "X-Scanner-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


def hash_api_key(api_key: str) -> str:
    """Hash an API key for storage."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def generate_api_key() -> str:
    """Generate a new random API key."""
    return secrets.token_urlsafe(32)


async def get_authenticated_scanner(
    api_key: Annotated[str, Security(api_key_header)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ScannerModel:
    """Authenticate a scanner device using its API key."""
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Scanner API Key",
        )

    key_hash = hash_api_key(api_key)
    result = await db.execute(
        select(ScannerModel).where(
            ScannerModel.api_key_hash == key_hash,
            ScannerModel.is_active == True
        )
    )
    scanner = result.scalar_one_or_none()

    if not scanner:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive Scanner API Key",
        )

    return scanner
