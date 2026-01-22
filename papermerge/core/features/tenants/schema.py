# (c) Copyright Datacraft, 2026
"""Tenant Pydantic schemas."""
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class TenantCreate(BaseModel):
	"""Schema for creating a tenant."""
	name: str
	slug: str
	plan: str = "free"
	custom_domain: str | None = None
	subdomain: str | None = None
	contact_email: str | None = None
	contact_phone: str | None = None
	billing_email: str | None = None
	max_users: int | None = None
	max_storage_gb: int | None = None
	features: dict[str, bool] | None = None


class TenantUpdate(BaseModel):
	"""Schema for updating a tenant."""
	name: str | None = None
	plan: str | None = None
	custom_domain: str | None = None
	subdomain: str | None = None
	contact_email: str | None = None
	contact_phone: str | None = None
	billing_email: str | None = None
	max_users: int | None = None
	max_storage_gb: int | None = None
	status: str | None = None
	features: dict[str, bool] | None = None


class TenantInfo(BaseModel):
	"""Basic tenant information."""
	id: UUID
	name: str
	slug: str
	status: str
	plan: str = "free"
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
	plan: str = "free"
	custom_domain: str | None = None
	subdomain: str | None = None
	contact_email: str | None = None
	contact_phone: str | None = None
	billing_email: str | None = None
	stripe_customer_id: str | None = None
	max_users: int | None = None
	max_storage_gb: int | None = None
	trial_ends_at: datetime | None = None
	created_at: datetime | None = None
	updated_at: datetime | None = None
	features: dict[str, bool] | None = None
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


# Storage Configuration Schemas

class StorageConfigCreate(BaseModel):
	"""Create storage configuration."""
	provider: str = "local"  # local, s3, linode, azure, gcs
	bucket_name: str | None = None
	region: str | None = None
	endpoint_url: str | None = None
	access_key_id: str | None = None
	secret_access_key: str | None = None
	base_path: str = "documents/"
	archive_path: str | None = None


class StorageConfigInfo(BaseModel):
	"""Storage configuration (without secrets)."""
	provider: str = "local"
	bucket_name: str | None = None
	region: str | None = None
	endpoint_url: str | None = None
	base_path: str = "documents/"
	archive_path: str | None = None
	is_verified: bool = False
	last_verified_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


class StorageConfigUpdate(BaseModel):
	"""Update storage configuration."""
	provider: str | None = None
	bucket_name: str | None = None
	region: str | None = None
	endpoint_url: str | None = None
	access_key_id: str | None = None
	secret_access_key: str | None = None
	base_path: str | None = None
	archive_path: str | None = None


# AI Configuration Schemas

class AIConfigCreate(BaseModel):
	"""Create AI configuration."""
	provider: str = "openai"  # openai, anthropic, azure_openai, local
	api_key: str | None = None
	endpoint_url: str | None = None
	default_model: str = "gpt-4o-mini"
	embedding_model: str = "text-embedding-3-small"
	monthly_token_limit: int | None = None
	classification_enabled: bool = True
	extraction_enabled: bool = True
	summarization_enabled: bool = True
	chat_enabled: bool = False


class AIConfigInfo(BaseModel):
	"""AI configuration (without secrets)."""
	provider: str = "openai"
	endpoint_url: str | None = None
	default_model: str = "gpt-4o-mini"
	embedding_model: str = "text-embedding-3-small"
	monthly_token_limit: int | None = None
	tokens_used_this_month: int = 0
	classification_enabled: bool = True
	extraction_enabled: bool = True
	summarization_enabled: bool = True
	chat_enabled: bool = False

	model_config = ConfigDict(from_attributes=True)


class AIConfigUpdate(BaseModel):
	"""Update AI configuration."""
	provider: str | None = None
	api_key: str | None = None
	endpoint_url: str | None = None
	default_model: str | None = None
	embedding_model: str | None = None
	monthly_token_limit: int | None = None
	classification_enabled: bool | None = None
	extraction_enabled: bool | None = None
	summarization_enabled: bool | None = None
	chat_enabled: bool | None = None


# Subscription Schemas

class SubscriptionCreate(BaseModel):
	"""Create subscription."""
	plan: str = "free"  # free, starter, professional, enterprise, custom
	billing_cycle: str = "monthly"  # monthly, annual
	max_users: int | None = None
	max_storage_gb: int | None = None
	max_documents: int | None = None
	ai_tokens_per_month: int | None = None
	addons: dict | None = None


class SubscriptionInfo(BaseModel):
	"""Subscription information."""
	plan: str = "free"
	billing_cycle: str = "monthly"
	current_period_start: datetime | None = None
	current_period_end: datetime | None = None
	cancel_at_period_end: bool = False
	max_users: int | None = None
	max_storage_gb: int | None = None
	max_documents: int | None = None
	ai_tokens_per_month: int | None = None
	addons: dict | None = None

	model_config = ConfigDict(from_attributes=True)


class SubscriptionUpdate(BaseModel):
	"""Update subscription."""
	plan: str | None = None
	billing_cycle: str | None = None
	max_users: int | None = None
	max_storage_gb: int | None = None
	max_documents: int | None = None
	ai_tokens_per_month: int | None = None
	cancel_at_period_end: bool | None = None
	addons: dict | None = None


# Full tenant provisioning schema

class TenantProvisionRequest(BaseModel):
	"""Full tenant provisioning request (system admin)."""
	# Basic info
	name: str
	slug: str
	contact_email: str
	billing_email: str | None = None

	# Subscription
	plan: str = "starter"
	billing_cycle: str = "monthly"

	# Storage
	storage_provider: str = "s3"
	storage_bucket: str | None = None
	storage_region: str = "us-east-1"
	storage_endpoint: str | None = None  # For Linode/MinIO

	# AI
	ai_provider: str = "openai"
	ai_monthly_tokens: int | None = None

	# Limits
	max_users: int = 5
	max_storage_gb: int = 10

	# Initial admin user
	admin_email: str
	admin_password: str | None = None  # If None, send setup email


class TenantProvisionResponse(BaseModel):
	"""Tenant provisioning response."""
	tenant: TenantInfo
	storage_configured: bool
	ai_configured: bool
	admin_user_id: UUID | None = None
	setup_link: str | None = None
