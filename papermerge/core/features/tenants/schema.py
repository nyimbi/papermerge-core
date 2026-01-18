# (c) Copyright Datacraft, 2026
"""Tenant Pydantic schemas."""
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class TenantCreate(BaseModel):
	"""Schema for creating a tenant."""
	name: str
	slug: str
	contact_email: str | None = None
	contact_phone: str | None = None
	billing_email: str | None = None
	max_users: int | None = None
	max_storage_gb: int | None = None


class TenantUpdate(BaseModel):
	"""Schema for updating a tenant."""
	name: str | None = None
	contact_email: str | None = None
	contact_phone: str | None = None
	billing_email: str | None = None
	max_users: int | None = None
	max_storage_gb: int | None = None
	status: str | None = None


class TenantInfo(BaseModel):
	"""Basic tenant information."""
	id: UUID
	name: str
	slug: str
	status: str
	created_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


class TenantBrandingInfo(BaseModel):
	"""Tenant branding information."""
	logo_url: str | None = None
	logo_dark_url: str | None = None
	favicon_url: str | None = None
	primary_color: str = "#228be6"
	secondary_color: str = "#868e96"
	login_background_url: str | None = None
	login_message: str | None = None

	model_config = ConfigDict(from_attributes=True)


class TenantSettingsInfo(BaseModel):
	"""Tenant settings information."""
	document_numbering_scheme: str = "{YEAR}-{SEQ:6}"
	default_language: str = "en"
	storage_quota_gb: int | None = None
	warn_at_percentage: int = 80
	default_retention_days: int | None = None
	auto_archive_days: int | None = None
	ocr_enabled: bool = True
	ai_features_enabled: bool = True
	workflow_enabled: bool = True
	encryption_enabled: bool = False

	model_config = ConfigDict(from_attributes=True)


class TenantDetail(BaseModel):
	"""Detailed tenant information."""
	id: UUID
	name: str
	slug: str
	status: str
	contact_email: str | None = None
	contact_phone: str | None = None
	billing_email: str | None = None
	stripe_customer_id: str | None = None
	max_users: int | None = None
	max_storage_gb: int | None = None
	trial_ends_at: datetime | None = None
	created_at: datetime | None = None
	updated_at: datetime | None = None
	branding: TenantBrandingInfo | None = None
	settings: TenantSettingsInfo | None = None

	model_config = ConfigDict(from_attributes=True)


class TenantListResponse(BaseModel):
	"""Paginated tenant list."""
	items: list[TenantInfo]
	total: int
	page: int
	page_size: int


class BrandingUpdate(BaseModel):
	"""Schema for updating tenant branding."""
	logo_url: str | None = None
	logo_dark_url: str | None = None
	favicon_url: str | None = None
	primary_color: str | None = None
	secondary_color: str | None = None
	login_background_url: str | None = None
	login_message: str | None = None
	email_header_html: str | None = None
	email_footer_html: str | None = None


class SettingsUpdate(BaseModel):
	"""Schema for updating tenant settings."""
	document_numbering_scheme: str | None = None
	default_language: str | None = None
	storage_quota_gb: int | None = None
	warn_at_percentage: int | None = None
	default_retention_days: int | None = None
	auto_archive_days: int | None = None
	ocr_enabled: bool | None = None
	ai_features_enabled: bool | None = None
	workflow_enabled: bool | None = None
	encryption_enabled: bool | None = None


class TenantUsageInfo(BaseModel):
	"""Tenant usage statistics."""
	tenant_id: UUID
	total_users: int
	total_documents: int
	storage_used_bytes: int
	storage_quota_bytes: int | None = None
	storage_percentage: float | None = None
