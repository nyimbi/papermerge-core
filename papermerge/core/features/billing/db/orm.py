# (c) Copyright Datacraft, 2026
"""
ORM models for resource usage and billing.
"""
import enum
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
	String,
	Integer,
	Text,
	ForeignKey,
	DateTime,
	Date,
	Enum,
	Numeric,
	BigInteger,
	UniqueConstraint,
	Index,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid_extensions import uuid7str

from papermerge.core.db.base import Base

if TYPE_CHECKING:
	from papermerge.core.features.tenants.db.orm import Tenant


class ProviderType(str, enum.Enum):
	"""Cloud provider types."""
	AWS = "aws"
	LINODE = "linode"
	CLOUDFLARE = "cloudflare"
	DIGITALOCEAN = "digitalocean"
	GCP = "gcp"
	AZURE = "azure"
	CUSTOM = "custom"


class ServiceType(str, enum.Enum):
	"""Types of billable services."""
	STORAGE = "storage"
	TRANSFER_OUT = "transfer_out"
	TRANSFER_IN = "transfer_in"
	COMPUTE = "compute"
	API_CALLS = "api_calls"
	OCR_PAGES = "ocr_pages"
	SEARCH_QUERIES = "search_queries"
	DOCUMENTS = "documents"
	USERS = "users"


class AlertType(str, enum.Enum):
	"""Types of usage alerts."""
	STORAGE_THRESHOLD = "storage_threshold"
	TRANSFER_THRESHOLD = "transfer_threshold"
	COST_THRESHOLD = "cost_threshold"
	DOCUMENT_LIMIT = "document_limit"
	USER_LIMIT = "user_limit"
	API_RATE_LIMIT = "api_rate_limit"


class AlertStatus(str, enum.Enum):
	"""Alert status."""
	ACTIVE = "active"
	TRIGGERED = "triggered"
	RESOLVED = "resolved"
	DISABLED = "disabled"


class InvoiceStatus(str, enum.Enum):
	"""Invoice status."""
	DRAFT = "draft"
	PENDING = "pending"
	SENT = "sent"
	PAID = "paid"
	OVERDUE = "overdue"
	CANCELLED = "cancelled"
	REFUNDED = "refunded"


class CloudProvider(Base):
	"""
	Configuration for a cloud provider used for cost tracking.
	"""
	__tablename__ = "cloud_providers"

	id: Mapped[str] = mapped_column(
		String(32),
		primary_key=True,
		default=uuid7str,
	)
	name: Mapped[str] = mapped_column(String(100), nullable=False)
	provider_type: Mapped[ProviderType] = mapped_column(Enum(ProviderType))
	# Encrypted credentials stored as JSON
	credentials_encrypted: Mapped[str | None] = mapped_column(Text)
	# Provider-specific configuration
	config: Mapped[dict | None] = mapped_column(JSONB)
	# Account/subscription ID
	account_id: Mapped[str | None] = mapped_column(String(100))
	region: Mapped[str | None] = mapped_column(String(50))
	is_active: Mapped[bool] = mapped_column(default=True)

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		DateTime,
		default=datetime.utcnow,
	)
	updated_at: Mapped[datetime] = mapped_column(
		DateTime,
		default=datetime.utcnow,
		onupdate=datetime.utcnow,
	)
	# Tenant isolation (null = system-wide)
	tenant_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"),
	)

	# Relationships
	pricing_tiers: Mapped[list["PricingTier"]] = relationship(
		"PricingTier",
		back_populates="provider",
	)

	__table_args__ = (
		Index("ix_cloud_providers_tenant", "tenant_id"),
		Index("ix_cloud_providers_type", "provider_type"),
	)


class PricingTier(Base):
	"""
	Pricing configuration for services.
	"""
	__tablename__ = "pricing_tiers"

	id: Mapped[str] = mapped_column(
		String(32),
		primary_key=True,
		default=uuid7str,
	)
	provider_id: Mapped[str] = mapped_column(
		String(32),
		ForeignKey("cloud_providers.id", ondelete="CASCADE"),
	)
	service: Mapped[ServiceType] = mapped_column(Enum(ServiceType))
	name: Mapped[str | None] = mapped_column(String(100))
	description: Mapped[str | None] = mapped_column(Text)

	# Pricing (in cents per unit)
	# e.g., storage_per_gb_month = 2.3 cents = $0.023/GB/month
	unit_price_cents: Mapped[Decimal] = mapped_column(
		Numeric(12, 4),
		default=0,
	)
	unit_name: Mapped[str] = mapped_column(String(50), default="unit")
	# e.g., "GB", "1000 requests", "page"

	# Tiered pricing thresholds (optional)
	min_units: Mapped[int] = mapped_column(BigInteger, default=0)
	max_units: Mapped[int | None] = mapped_column(BigInteger)
	# null = unlimited

	# Free tier
	free_tier_units: Mapped[int] = mapped_column(BigInteger, default=0)

	# Effective dates
	effective_from: Mapped[date] = mapped_column(Date, default=date.today)
	effective_to: Mapped[date | None] = mapped_column(Date)

	is_active: Mapped[bool] = mapped_column(default=True)

	# Relationships
	provider: Mapped["CloudProvider"] = relationship(
		"CloudProvider",
		back_populates="pricing_tiers",
	)

	__table_args__ = (
		Index("ix_pricing_tiers_provider", "provider_id"),
		Index("ix_pricing_tiers_service", "service"),
		UniqueConstraint(
			"provider_id", "service", "min_units",
			name="uq_pricing_tier_provider_service_min",
		),
	)


class UsageDaily(Base):
	"""
	Daily usage records per tenant.
	"""
	__tablename__ = "usage_daily"

	id: Mapped[str] = mapped_column(
		String(32),
		primary_key=True,
		default=uuid7str,
	)
	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"),
	)
	usage_date: Mapped[date] = mapped_column(Date, nullable=False)

	# Storage metrics (in bytes)
	storage_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
	storage_hot_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
	storage_cold_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
	storage_archive_bytes: Mapped[int] = mapped_column(BigInteger, default=0)

	# Transfer metrics (in bytes)
	transfer_in_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
	transfer_out_bytes: Mapped[int] = mapped_column(BigInteger, default=0)

	# Document metrics
	documents_count: Mapped[int] = mapped_column(Integer, default=0)
	documents_added: Mapped[int] = mapped_column(Integer, default=0)
	documents_deleted: Mapped[int] = mapped_column(Integer, default=0)
	pages_processed: Mapped[int] = mapped_column(Integer, default=0)

	# API metrics
	api_calls: Mapped[int] = mapped_column(Integer, default=0)
	search_queries: Mapped[int] = mapped_column(Integer, default=0)

	# User metrics
	active_users: Mapped[int] = mapped_column(Integer, default=0)

	# Calculated costs (in cents)
	storage_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
	transfer_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
	compute_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
	cost_total_cents: Mapped[int] = mapped_column(Integer, default=0)

	# Detailed cost breakdown
	cost_breakdown: Mapped[dict | None] = mapped_column(JSONB)

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		DateTime,
		default=datetime.utcnow,
	)
	updated_at: Mapped[datetime] = mapped_column(
		DateTime,
		default=datetime.utcnow,
		onupdate=datetime.utcnow,
	)

	__table_args__ = (
		UniqueConstraint("tenant_id", "usage_date", name="uq_usage_daily_tenant_date"),
		Index("ix_usage_daily_tenant", "tenant_id"),
		Index("ix_usage_daily_date", "usage_date"),
	)


class UsageAlert(Base):
	"""
	Usage alerts and budget thresholds.
	"""
	__tablename__ = "usage_alerts"

	id: Mapped[str] = mapped_column(
		String(32),
		primary_key=True,
		default=uuid7str,
	)
	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"),
	)
	alert_type: Mapped[AlertType] = mapped_column(Enum(AlertType))
	name: Mapped[str] = mapped_column(String(100), nullable=False)
	description: Mapped[str | None] = mapped_column(Text)

	# Threshold configuration
	threshold_value: Mapped[Decimal] = mapped_column(Numeric(16, 4))
	threshold_unit: Mapped[str] = mapped_column(String(50))
	# e.g., "GB", "cents", "documents"

	# Current value (updated by background task)
	current_value: Mapped[Decimal] = mapped_column(
		Numeric(16, 4),
		default=0,
	)
	percentage_used: Mapped[Decimal] = mapped_column(
		Numeric(5, 2),
		default=0,
	)

	# Alert status
	status: Mapped[AlertStatus] = mapped_column(
		Enum(AlertStatus),
		default=AlertStatus.ACTIVE,
	)

	# Notification settings
	notify_at_percentage: Mapped[list[int]] = mapped_column(
		JSONB,
		default=list,
	)  # e.g., [50, 75, 90, 100]
	notifications_sent: Mapped[list[int]] = mapped_column(
		JSONB,
		default=list,
	)
	notification_channels: Mapped[list[str]] = mapped_column(
		JSONB,
		default=list,
	)  # e.g., ["email", "slack", "webhook"]

	# Trigger history
	last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime)
	triggered_count: Mapped[int] = mapped_column(Integer, default=0)

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		DateTime,
		default=datetime.utcnow,
	)
	updated_at: Mapped[datetime] = mapped_column(
		DateTime,
		default=datetime.utcnow,
		onupdate=datetime.utcnow,
	)

	__table_args__ = (
		Index("ix_usage_alerts_tenant", "tenant_id"),
		Index("ix_usage_alerts_type", "alert_type"),
		Index("ix_usage_alerts_status", "status"),
	)


class Invoice(Base):
	"""
	Invoice records for billing.
	"""
	__tablename__ = "invoices"

	id: Mapped[str] = mapped_column(
		String(32),
		primary_key=True,
		default=uuid7str,
	)
	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"),
	)

	# Invoice identification
	invoice_number: Mapped[str] = mapped_column(String(50), unique=True)
	reference: Mapped[str | None] = mapped_column(String(100))

	# Billing period
	period_start: Mapped[date] = mapped_column(Date, nullable=False)
	period_end: Mapped[date] = mapped_column(Date, nullable=False)

	# Status
	status: Mapped[InvoiceStatus] = mapped_column(
		Enum(InvoiceStatus),
		default=InvoiceStatus.DRAFT,
	)

	# Amounts (in cents)
	subtotal_cents: Mapped[int] = mapped_column(Integer, default=0)
	discount_cents: Mapped[int] = mapped_column(Integer, default=0)
	tax_cents: Mapped[int] = mapped_column(Integer, default=0)
	total_cents: Mapped[int] = mapped_column(Integer, default=0)
	paid_cents: Mapped[int] = mapped_column(Integer, default=0)
	balance_due_cents: Mapped[int] = mapped_column(Integer, default=0)

	# Currency
	currency: Mapped[str] = mapped_column(String(3), default="USD")

	# Billing details
	billing_name: Mapped[str | None] = mapped_column(String(200))
	billing_email: Mapped[str | None] = mapped_column(String(200))
	billing_address: Mapped[dict | None] = mapped_column(JSONB)

	# Payment
	payment_method: Mapped[str | None] = mapped_column(String(50))
	payment_id: Mapped[str | None] = mapped_column(String(100))
	paid_at: Mapped[datetime | None] = mapped_column(DateTime)

	# Dates
	issued_at: Mapped[datetime | None] = mapped_column(DateTime)
	due_date: Mapped[date | None] = mapped_column(Date)

	# Notes
	notes: Mapped[str | None] = mapped_column(Text)
	internal_notes: Mapped[str | None] = mapped_column(Text)

	# PDF storage
	pdf_path: Mapped[str | None] = mapped_column(String(500))

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		DateTime,
		default=datetime.utcnow,
	)
	updated_at: Mapped[datetime] = mapped_column(
		DateTime,
		default=datetime.utcnow,
		onupdate=datetime.utcnow,
	)

	# Relationships
	line_items: Mapped[list["InvoiceLineItem"]] = relationship(
		"InvoiceLineItem",
		back_populates="invoice",
		cascade="all, delete-orphan",
	)

	__table_args__ = (
		Index("ix_invoices_tenant", "tenant_id"),
		Index("ix_invoices_status", "status"),
		Index("ix_invoices_period", "period_start", "period_end"),
	)


class InvoiceLineItem(Base):
	"""
	Individual line items on an invoice.
	"""
	__tablename__ = "invoice_line_items"

	id: Mapped[str] = mapped_column(
		String(32),
		primary_key=True,
		default=uuid7str,
	)
	invoice_id: Mapped[str] = mapped_column(
		String(32),
		ForeignKey("invoices.id", ondelete="CASCADE"),
	)
	# Display order
	line_number: Mapped[int] = mapped_column(Integer, default=0)

	# Item details
	description: Mapped[str] = mapped_column(String(500), nullable=False)
	service_type: Mapped[ServiceType | None] = mapped_column(Enum(ServiceType))

	# Quantity and pricing
	quantity: Mapped[Decimal] = mapped_column(Numeric(16, 4), default=1)
	unit_name: Mapped[str] = mapped_column(String(50), default="unit")
	unit_price_cents: Mapped[int] = mapped_column(Integer, default=0)

	# Calculated amounts
	subtotal_cents: Mapped[int] = mapped_column(Integer, default=0)
	discount_cents: Mapped[int] = mapped_column(Integer, default=0)
	tax_cents: Mapped[int] = mapped_column(Integer, default=0)
	total_cents: Mapped[int] = mapped_column(Integer, default=0)

	# Tax details
	tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
	tax_code: Mapped[str | None] = mapped_column(String(50))

	# Metadata
	metadata: Mapped[dict | None] = mapped_column(JSONB)

	# Relationships
	invoice: Mapped["Invoice"] = relationship(
		"Invoice",
		back_populates="line_items",
	)

	__table_args__ = (
		Index("ix_invoice_line_items_invoice", "invoice_id"),
	)
