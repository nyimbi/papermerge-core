"""
API Keys router — /api-keys

Provides CRUD for tenant-scoped API keys used by external integrations.
Keys are identified by a dak_ prefix. Plaintext is returned only on creation.
"""
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core import db, scopes
from papermerge.core.features.api_keys.db.orm import ApiKey
from papermerge.core.features.api_keys.hashing import hash_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api-keys", tags=["api-keys"])

API_KEY_PREFIX = "dak_"

# ---------------------------------------------------------------------------
# Pydantic schemas (inlined — feature is self-contained)
# ---------------------------------------------------------------------------

class ApiKeyResponse(BaseModel):
	"""Safe representation — never includes hash or plaintext."""
	id: UUID
	name: str
	key_prefix: str
	scopes: list[str]
	last_used_at: datetime | None
	expires_at: datetime | None
	is_active: bool
	created_at: datetime

	model_config = ConfigDict(from_attributes=True)

	@classmethod
	def from_orm(cls, obj: ApiKey) -> "ApiKeyResponse":
		return cls(
			id=obj.id,
			name=obj.name,
			key_prefix=obj.key_prefix,
			scopes=obj.scope_list,
			last_used_at=obj.last_used_at,
			expires_at=obj.expires_at,
			is_active=obj.is_active,
			created_at=obj.created_at,
		)


class ApiKeyCreate(BaseModel):
	name: str = Field(..., min_length=1, max_length=255)
	scopes: list[str] = Field(
		default_factory=list,
		description='e.g. ["read", "write", "webhooks", "admin"]',
	)
	expires_at: datetime | None = Field(
		default=None,
		description="Optional ISO-8601 expiry datetime. Omit for no expiry.",
	)


class ApiKeyCreated(ApiKeyResponse):
	"""Returned only at creation — includes one-time plaintext key."""
	key: str = Field(description="Plaintext key. Copy now — shown only once.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_key() -> tuple[str, str, str]:
	"""Returns (plaintext, key_hash, key_prefix)."""
	plaintext = API_KEY_PREFIX + secrets.token_urlsafe(32)
	key_hash = hash_key(plaintext)
	key_prefix = plaintext[:8]
	return plaintext, key_hash, key_prefix


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
	"",
	response_model=list[ApiKeyResponse],
	summary="List API keys for the current user's tenant",
)
async def list_api_keys(
	user: scopes.ViewAPIToken,
	db_session: db.DBRouterAsyncSession,
) -> list[ApiKeyResponse]:
	stmt = (
		select(ApiKey)
		.where(
			ApiKey.created_by_id == user.id,
			ApiKey.is_active.is_(True),
		)
		.order_by(ApiKey.created_at.desc())
	)
	result = await db_session.execute(stmt)
	rows = list(result.scalars().all())
	return [ApiKeyResponse.from_orm(r) for r in rows]


@router.post(
	"",
	response_model=ApiKeyCreated,
	status_code=status.HTTP_201_CREATED,
	summary="Create a new API key",
	description="""
Create a new API key for external integrations.

**IMPORTANT**: The plaintext `key` is only returned in this response.
It cannot be retrieved later — store it securely immediately.

Use in requests as:
```
Authorization: Bearer dak_xxxxx...
```
""",
)
async def create_api_key(
	body: ApiKeyCreate,
	user: scopes.CreateAPIToken,
	db_session: db.DBRouterAsyncSession,
) -> ApiKeyCreated:
	plaintext, key_hash, key_prefix = _generate_key()

	# Resolve tenant_id from user (multi-tenant: user.node_id lives under a tenant)
	# Fall back to user.id cast to UUID if tenant not set — acceptable for single-tenant
	tenant_id: UUID = getattr(user, "tenant_id", None) or user.id

	api_key = ApiKey(
		id=uuid4(),
		name=body.name,
		key_hash=key_hash,
		key_prefix=key_prefix,
		scopes=json.dumps(body.scopes),
		expires_at=body.expires_at,
		is_active=True,
		created_by_id=user.id,
		tenant_id=tenant_id,
	)
	db_session.add(api_key)
	await db_session.commit()
	await db_session.refresh(api_key)

	logger.info(
		"API key created: prefix=%s user=%s tenant=%s",
		key_prefix,
		user.id,
		tenant_id,
	)

	return ApiKeyCreated(
		id=api_key.id,
		name=api_key.name,
		key_prefix=api_key.key_prefix,
		scopes=api_key.scope_list,
		last_used_at=api_key.last_used_at,
		expires_at=api_key.expires_at,
		is_active=api_key.is_active,
		created_at=api_key.created_at,
		key=plaintext,
	)


@router.delete(
	"/{key_id}",
	status_code=status.HTTP_204_NO_CONTENT,
	summary="Revoke an API key",
)
async def revoke_api_key(
	key_id: UUID,
	user: scopes.DeleteAPIToken,
	db_session: db.DBRouterAsyncSession,
) -> None:
	stmt = select(ApiKey).where(
		ApiKey.id == key_id,
		ApiKey.created_by_id == user.id,
	)
	result = await db_session.execute(stmt)
	api_key: ApiKey | None = result.scalar_one_or_none()

	if api_key is None:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail="API key not found",
		)

	await db_session.execute(
		update(ApiKey)
		.where(ApiKey.id == key_id)
		.values(is_active=False)
	)
	await db_session.commit()

	logger.info(
		"API key revoked: id=%s prefix=%s user=%s",
		key_id,
		api_key.key_prefix,
		user.id,
	)
