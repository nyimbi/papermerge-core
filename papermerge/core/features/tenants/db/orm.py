# (c) Copyright Datacraft, 2026
"""Tenant ORM models for multi-tenancy."""
import uuid
from datetime import datetime
from uuid import UUID
from enum import Enum

from sqlalchemy import String, ForeignKey, Integer, Boolean, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import TIMESTAMP, JSONB

from papermerge.core.db.base import Base
from papermerge.core.utils.tz import utc_now


class TenantStatus(str, Enum):
	ACTIVE = "active"
	SUSPENDED = "suspended"
	TRIAL = "trial"
	CANCELLED = "cancelled"


class Tenant(Base):
	"""Multi-tenant organization."""
	__tablename__ = "tenants"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	name: Mapped[str] = mapped_column(String(255), nullable=False)
	slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
	status: Mapped[str] = mapped_column(String(20), default=TenantStatus.ACTIVE.value)

	# Domain configuration
	custom_domain: Mapped[str | None] = mapped_column(String(255), unique=True)
	subdomain: Mapped[str | None] = mapped_column(String(100))

	# Plan and features
	plan: Mapped[str] = mapped_column(String(50), default="free")
	features: Mapped[dict | None] = mapped_column(JSONB)  # Feature flag overrides

	# Contact
	contact_email: Mapped[str | None] = mapped_column(String(255))
	contact_phone: Mapped[str | None] = mapped_column(String(50))

	# Billing
	billing_email: Mapped[str | None] = mapped_column(String(255))
	stripe_customer_id: Mapped[str | None] = mapped_column(String(100))

	# Limits
	max_users: Mapped[int | None] = mapped_column(Integer)
	max_storage_gb: Mapped[int | None] = mapped_column(Integer)

	# Trial
	trial_ends_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)
	updated_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, onupdate=func.now(), nullable=False
	)

	# Relationships
	branding: Mapped["TenantBranding"] = relationship(
		"TenantBranding", back_populates="tenant", uselist=False, cascade="all, delete-orphan"
	)
	settings: Mapped["TenantSettings"] = relationship(
		"TenantSettings", back_populates="tenant", uselist=False, cascade="all, delete-orphan"
	)
	policies = relationship(
		"PolicyModel", back_populates="tenant", cascade="all, delete-orphan"
	)
	users = relationship(
		"User", back_populates="tenant", cascade="all, delete-orphan"
	)

	def __repr__(self):
		return f"Tenant(id={self.id}, name={self.name})"


class TenantBranding(Base):
	"""Tenant branding and customization."""
	__tablename__ = "tenant_branding"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, nullable=False
	)

	# Logo
	logo_url: Mapped[str | None] = mapped_column(String(500))
	logo_dark_url: Mapped[str | None] = mapped_column(String(500))
	favicon_url: Mapped[str | None] = mapped_column(String(500))

	# Colors
	primary_color: Mapped[str] = mapped_column(String(20), default="#228be6")
	secondary_color: Mapped[str] = mapped_column(String(20), default="#868e96")

	# Login page
	login_background_url: Mapped[str | None] = mapped_column(String(500))
	login_message: Mapped[str | None] = mapped_column(Text)

	# Email templates
	email_header_html: Mapped[str | None] = mapped_column(Text)
	email_footer_html: Mapped[str | None] = mapped_column(Text)

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)
	updated_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, onupdate=func.now(), nullable=False
	)

	# Relationships
	tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="branding")


class TenantSettings(Base):
	"""Tenant configuration settings."""
	__tablename__ = "tenant_settings"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, nullable=False
	)

	# Document settings
	document_numbering_scheme: Mapped[str] = mapped_column(
		String(100), default="{YEAR}-{SEQ:6}"
	)
	default_language: Mapped[str] = mapped_column(String(10), default="en")

	# Storage
	storage_quota_gb: Mapped[int | None] = mapped_column(Integer)
	warn_at_percentage: Mapped[int] = mapped_column(Integer, default=80)

	# Retention
	default_retention_days: Mapped[int | None] = mapped_column(Integer)
	auto_archive_days: Mapped[int | None] = mapped_column(Integer)

	# Features
	ocr_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
	ai_features_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
	workflow_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
	encryption_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)
	updated_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, onupdate=func.now(), nullable=False
	)

	# Relationships
	tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="settings")


class StorageProvider(str, Enum):
	LOCAL = "local"
	S3 = "s3"
	LINODE = "linode"
	AZURE = "azure"
	GCS = "gcs"


class TenantStorageConfig(Base):
	"""Tenant cloud storage configuration."""
	__tablename__ = "tenant_storage_config"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, nullable=False
	)

	# Provider configuration
	provider: Mapped[str] = mapped_column(String(20), default=StorageProvider.LOCAL.value)
	bucket_name: Mapped[str | None] = mapped_column(String(255))
	region: Mapped[str | None] = mapped_column(String(50))
	endpoint_url: Mapped[str | None] = mapped_column(String(500))  # For S3-compatible (Linode)

	# Credentials (encrypted at rest)
	access_key_id: Mapped[str | None] = mapped_column(String(255))
	secret_access_key: Mapped[str | None] = mapped_column(String(500))  # Encrypted

	# Path configuration
	base_path: Mapped[str] = mapped_column(String(500), default="documents/")
	archive_path: Mapped[str | None] = mapped_column(String(500))

	# Verification
	is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
	last_verified_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)
	updated_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, onupdate=func.now(), nullable=False
	)


class AIProvider(str, Enum):
	OPENAI = "openai"
	ANTHROPIC = "anthropic"
	AZURE_OPENAI = "azure_openai"
	LOCAL = "local"


class TenantAIConfig(Base):
	"""Tenant AI/ML service configuration."""
	__tablename__ = "tenant_ai_config"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, nullable=False
	)

	# Provider
	provider: Mapped[str] = mapped_column(String(20), default=AIProvider.OPENAI.value)
	api_key: Mapped[str | None] = mapped_column(String(500))  # Encrypted
	endpoint_url: Mapped[str | None] = mapped_column(String(500))  # For Azure/local

	# Models
	default_model: Mapped[str] = mapped_column(String(100), default="gpt-4o-mini")
	embedding_model: Mapped[str] = mapped_column(String(100), default="text-embedding-3-small")

	# Limits
	monthly_token_limit: Mapped[int | None] = mapped_column(Integer)
	tokens_used_this_month: Mapped[int] = mapped_column(Integer, default=0)
	token_reset_day: Mapped[int] = mapped_column(Integer, default=1)  # Day of month to reset

	# Features
	classification_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
	extraction_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
	summarization_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
	chat_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)
	updated_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, onupdate=func.now(), nullable=False
	)


class SubscriptionPlan(str, Enum):
	FREE = "free"
	STARTER = "starter"
	PROFESSIONAL = "professional"
	ENTERPRISE = "enterprise"
	CUSTOM = "custom"


class TenantSubscription(Base):
	"""Tenant SaaS subscription management."""
	__tablename__ = "tenant_subscriptions"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, nullable=False
	)

	# Plan
	plan: Mapped[str] = mapped_column(String(50), default=SubscriptionPlan.FREE.value)
	billing_cycle: Mapped[str] = mapped_column(String(20), default="monthly")  # monthly, annual

	# Stripe
	stripe_subscription_id: Mapped[str | None] = mapped_column(String(100))
	stripe_price_id: Mapped[str | None] = mapped_column(String(100))

	# Dates
	current_period_start: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
	current_period_end: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
	cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
	canceled_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

	# Plan limits (copied from plan at subscription time, can be overridden)
	max_users: Mapped[int | None] = mapped_column(Integer)
	max_storage_gb: Mapped[int | None] = mapped_column(Integer)
	max_documents: Mapped[int | None] = mapped_column(Integer)
	ai_tokens_per_month: Mapped[int | None] = mapped_column(Integer)

	# Addons (JSON list of addon IDs/features)
	addons: Mapped[dict | None] = mapped_column(JSONB)

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)
	updated_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, onupdate=func.now(), nullable=False
	)
