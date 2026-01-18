# (c) Copyright Datacraft, 2026
"""
Pydantic schemas for billing.
"""
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field
from uuid import UUID

from .db.orm import (
	ProviderType,
	ServiceType,
	AlertType,
	AlertStatus,
	InvoiceStatus,
)


# ============ Cloud Provider Schemas ============

class CloudProviderBase(BaseModel):
	name: str = Field(..., min_length=1, max_length=100)
	provider_type: ProviderType
	account_id: str | None = Field(None, max_length=100)
	region: str | None = Field(None, max_length=50)
	config: dict | None = None
	is_active: bool = True


class CloudProviderCreate(CloudProviderBase):
	credentials: dict  # Will be encrypted before storage


class CloudProviderUpdate(BaseModel):
	name: str | None = Field(None, min_length=1, max_length=100)
	account_id: str | None = Field(None, max_length=100)
	region: str | None = Field(None, max_length=50)
	config: dict | None = None
	is_active: bool | None = None
	credentials: dict | None = None  # Optional credential update


class CloudProvider(CloudProviderBase):
	model_config = ConfigDict(from_attributes=True)

	id: str
	tenant_id: UUID | None = None
	created_at: datetime
	updated_at: datetime


# ============ Pricing Tier Schemas ============

class PricingTierBase(BaseModel):
	service: ServiceType
	name: str | None = Field(None, max_length=100)
	description: str | None = None
	unit_price_cents: Decimal = Field(default=0, ge=0)
	unit_name: str = Field(default="unit", max_length=50)
	min_units: int = Field(default=0, ge=0)
	max_units: int | None = Field(None, ge=0)
	free_tier_units: int = Field(default=0, ge=0)
	effective_from: date | None = None
	effective_to: date | None = None
	is_active: bool = True


class PricingTierCreate(PricingTierBase):
	provider_id: str


class PricingTier(PricingTierBase):
	model_config = ConfigDict(from_attributes=True)

	id: str
	provider_id: str


# ============ Usage Schemas ============

class UsageDailyBase(BaseModel):
	usage_date: date
	storage_bytes: int = 0
	storage_hot_bytes: int = 0
	storage_cold_bytes: int = 0
	storage_archive_bytes: int = 0
	transfer_in_bytes: int = 0
	transfer_out_bytes: int = 0
	documents_count: int = 0
	documents_added: int = 0
	documents_deleted: int = 0
	pages_processed: int = 0
	api_calls: int = 0
	search_queries: int = 0
	active_users: int = 0


class UsageDaily(UsageDailyBase):
	model_config = ConfigDict(from_attributes=True)

	id: str
	tenant_id: UUID
	storage_cost_cents: int
	transfer_cost_cents: int
	compute_cost_cents: int
	cost_total_cents: int
	cost_breakdown: dict | None = None
	created_at: datetime
	updated_at: datetime


class UsageSummary(BaseModel):
	start_date: date
	end_date: date
	total_storage_bytes: int
	total_transfer_in_bytes: int
	total_transfer_out_bytes: int
	total_documents: int
	total_pages_processed: int
	total_api_calls: int
	peak_active_users: int
	total_cost_cents: int
	daily_average_cost_cents: int


# ============ Alert Schemas ============

class UsageAlertBase(BaseModel):
	alert_type: AlertType
	name: str = Field(..., min_length=1, max_length=100)
	description: str | None = None
	threshold_value: Decimal = Field(..., gt=0)
	threshold_unit: str = Field(..., max_length=50)
	notify_at_percentage: list[int] = Field(default=[50, 75, 90, 100])
	notification_channels: list[str] = Field(default=["email"])


class UsageAlertCreate(UsageAlertBase):
	pass


class UsageAlertUpdate(BaseModel):
	name: str | None = Field(None, min_length=1, max_length=100)
	description: str | None = None
	threshold_value: Decimal | None = Field(None, gt=0)
	notify_at_percentage: list[int] | None = None
	notification_channels: list[str] | None = None
	status: AlertStatus | None = None


class UsageAlert(UsageAlertBase):
	model_config = ConfigDict(from_attributes=True)

	id: str
	tenant_id: UUID
	current_value: Decimal
	percentage_used: Decimal
	status: AlertStatus
	notifications_sent: list[int]
	last_triggered_at: datetime | None
	triggered_count: int
	created_at: datetime
	updated_at: datetime


# ============ Invoice Schemas ============

class InvoiceLineItemBase(BaseModel):
	line_number: int = 0
	description: str = Field(..., min_length=1, max_length=500)
	service_type: ServiceType | None = None
	quantity: Decimal = Field(default=1, gt=0)
	unit_name: str = Field(default="unit", max_length=50)
	unit_price_cents: int = Field(default=0, ge=0)
	discount_cents: int = Field(default=0, ge=0)
	tax_rate: Decimal = Field(default=0, ge=0, le=100)
	tax_code: str | None = Field(None, max_length=50)


class InvoiceLineItemCreate(InvoiceLineItemBase):
	pass


class InvoiceLineItem(InvoiceLineItemBase):
	model_config = ConfigDict(from_attributes=True)

	id: str
	invoice_id: str
	subtotal_cents: int
	tax_cents: int
	total_cents: int
	metadata: dict | None = None


class InvoiceBase(BaseModel):
	reference: str | None = Field(None, max_length=100)
	period_start: date
	period_end: date
	currency: str = Field(default="USD", max_length=3)
	billing_name: str | None = Field(None, max_length=200)
	billing_email: str | None = Field(None, max_length=200)
	billing_address: dict | None = None
	notes: str | None = None


class InvoiceCreate(InvoiceBase):
	line_items: list[InvoiceLineItemCreate] = []


class InvoiceUpdate(BaseModel):
	status: InvoiceStatus | None = None
	billing_name: str | None = Field(None, max_length=200)
	billing_email: str | None = Field(None, max_length=200)
	billing_address: dict | None = None
	notes: str | None = None
	internal_notes: str | None = None


class Invoice(InvoiceBase):
	model_config = ConfigDict(from_attributes=True)

	id: str
	tenant_id: UUID
	invoice_number: str
	status: InvoiceStatus
	subtotal_cents: int
	discount_cents: int
	tax_cents: int
	total_cents: int
	paid_cents: int
	balance_due_cents: int
	payment_method: str | None
	payment_id: str | None
	paid_at: datetime | None
	issued_at: datetime | None
	due_date: date | None
	internal_notes: str | None
	pdf_path: str | None
	created_at: datetime
	updated_at: datetime
	line_items: list[InvoiceLineItem] = []


class InvoiceSummary(BaseModel):
	model_config = ConfigDict(from_attributes=True)

	id: str
	invoice_number: str
	period_start: date
	period_end: date
	status: InvoiceStatus
	total_cents: int
	paid_cents: int
	balance_due_cents: int
	due_date: date | None
	created_at: datetime


# ============ Dashboard Schemas ============

class BillingDashboard(BaseModel):
	current_month_cost_cents: int
	previous_month_cost_cents: int
	cost_change_percentage: float
	current_storage_bytes: int
	storage_limit_bytes: int | None
	current_transfer_bytes: int
	transfer_limit_bytes: int | None
	active_alerts: int
	triggered_alerts: int
	pending_invoices: int
	overdue_invoices: int
	cost_by_service: dict[str, int]
	daily_costs: list[dict]


class CostEstimate(BaseModel):
	storage_gb: Decimal
	transfer_gb: Decimal
	documents: int
	users: int
	estimated_monthly_cost_cents: int
	breakdown: list[dict]
