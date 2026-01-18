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
