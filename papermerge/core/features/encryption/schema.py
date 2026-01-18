# (c) Copyright Datacraft, 2026
"""Encryption Pydantic schemas."""
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class KeyInfo(BaseModel):
	"""Key encryption key information."""
	id: UUID
	key_version: int
	is_active: bool
	created_at: datetime | None = None
	rotated_at: datetime | None = None
	expires_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


class KeyListResponse(BaseModel):
	"""List of keys for tenant."""
	items: list[KeyInfo]
	active_version: int


class RotateKeyRequest(BaseModel):
	"""Request to rotate the encryption key."""
	expire_old_in_days: int = 30


class RotateKeyResponse(BaseModel):
	"""Response from key rotation."""
	success: bool
	new_version: int
	message: str | None = None


class DocumentEncryptionInfo(BaseModel):
	"""Document encryption information."""
	document_id: UUID
	is_encrypted: bool
	key_version: int | None = None
	algorithm: str | None = None
	created_at: datetime | None = None


class HiddenAccessRequest(BaseModel):
	"""Request to access a hidden document."""
	document_id: UUID
	reason: str
	duration_hours: int = 24


class HiddenAccessInfo(BaseModel):
	"""Hidden document access request information."""
	id: UUID
	document_id: UUID
	requested_by: UUID
	requested_at: datetime
	reason: str
	status: str
	approved_by: UUID | None = None
	approved_at: datetime | None = None
	expires_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


class HiddenAccessListResponse(BaseModel):
	"""Paginated access request list."""
	items: list[HiddenAccessInfo]
	total: int
	page: int
	page_size: int


class ApproveAccessRequest(BaseModel):
	"""Request to approve hidden document access."""
	duration_hours: int = 24


class SingleViewAccessResponse(BaseModel):
	"""Response with single-view access token."""
	access_token: str
	expires_at: datetime
	document_id: UUID


class ValidateAccessRequest(BaseModel):
	"""Request to validate access token."""
	access_token: str


class ValidateAccessResponse(BaseModel):
	"""Response from access validation."""
	valid: bool
	document_id: UUID | None = None
	expires_at: datetime | None = None
	view_count: int = 0
	max_views: int = 1
