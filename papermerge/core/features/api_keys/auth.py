"""
API Key authentication dependency.

Checks Authorization: Bearer dak_... header, looks up by SHA-256 hash,
updates last_used_at, and returns (tenant_id, created_by_id) for use
as the acting identity on authenticated endpoints.
"""
import hashlib
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.api_keys.db.orm import ApiKey

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)

API_KEY_PREFIX = "dak_"


def _is_api_key(token: str) -> bool:
	return token.startswith(API_KEY_PREFIX)


def _hash_key(plaintext: str) -> str:
	return hashlib.sha256(plaintext.encode()).hexdigest()


async def get_api_key_identity(
	request: Request,
	bearer: HTTPAuthorizationCredentials | None = Depends(_bearer),
	db_session: AsyncSession = Depends(get_db),
) -> tuple[UUID, UUID] | None:
	"""
	Optional dependency — returns (tenant_id, created_by_id) when a valid
	dak_ Bearer token is presented, else None.

	Raises HTTP 401 if the token has the dak_ prefix but is invalid/expired/revoked.
	"""
	if bearer is None or not bearer.credentials:
		return None

	token = bearer.credentials
	if not _is_api_key(token):
		return None

	key_hash = _hash_key(token)

	stmt = select(ApiKey).where(
		ApiKey.key_hash == key_hash,
		ApiKey.is_active.is_(True),
	)
	result = await db_session.execute(stmt)
	api_key: ApiKey | None = result.scalar_one_or_none()

	if api_key is None:
		raise HTTPException(
			status_code=status.HTTP_401_UNAUTHORIZED,
			detail="Invalid or revoked API key",
			headers={"WWW-Authenticate": "Bearer"},
		)

	if api_key.is_expired:
		raise HTTPException(
			status_code=status.HTTP_401_UNAUTHORIZED,
			detail="API key has expired",
			headers={"WWW-Authenticate": "Bearer"},
		)

	# Fire-and-forget last_used_at update (best-effort, no commit needed here)
	await db_session.execute(
		update(ApiKey)
		.where(ApiKey.id == api_key.id)
		.values(last_used_at=datetime.now(timezone.utc))
	)

	logger.debug(
		"API key authenticated: prefix=%s tenant=%s",
		api_key.key_prefix,
		api_key.tenant_id,
	)
	return api_key.tenant_id, api_key.created_by_id
