# (c) Copyright Datacraft, 2026
"""
API router for billing and usage tracking.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_extensions import uuid7str

from papermerge.core.db.engine import get_db
from papermerge.core.auth import get_current_user
from papermerge.core.features.users.db.orm import User

from .db.orm import (
	CloudProvider as CloudProviderORM,
	PricingTier as PricingTierORM,
	UsageDaily as UsageDailyORM,
	UsageAlert as UsageAlertORM,
	Invoice as InvoiceORM,
	InvoiceLineItem as InvoiceLineItemORM,
	AlertStatus,
	InvoiceStatus,
	ServiceType,
)
from .schema import (
	CloudProviderCreate,
	CloudProviderUpdate,
	CloudProvider,
	PricingTierCreate,
	PricingTier,
	UsageDaily,
	UsageSummary,
	UsageAlertCreate,
	UsageAlertUpdate,
	UsageAlert,
	InvoiceCreate,
	InvoiceUpdate,
	Invoice,
	InvoiceSummary,
	BillingDashboard,
	CostEstimate,
)
from .calculator import CostCalculator
from .alerts import UsageAlertManager

router = APIRouter(prefix="/billing", tags=["billing"])


# ============ Dashboard ============

@router.get("/dashboard", response_model=BillingDashboard)
async def get_billing_dashboard(
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
	tenant_id: UUID | None = None,
):
	"""Get billing dashboard overview."""
	# Use tenant from context or parameter
	tid = tenant_id  # In production, get from tenant context

	today = date.today()
	month_start = today.replace(day=1)
	prev_month_start = (month_start - timedelta(days=1)).replace(day=1)
	prev_month_end = month_start - timedelta(days=1)

	# Current month costs
	current_result = await db.execute(
		select(func.sum(UsageDailyORM.cost_total_cents))
		.where(UsageDailyORM.usage_date >= month_start)
	)
	current_cost = current_result.scalar() or 0

	# Previous month costs
	prev_result = await db.execute(
		select(func.sum(UsageDailyORM.cost_total_cents))
		.where(UsageDailyORM.usage_date >= prev_month_start)
		.where(UsageDailyORM.usage_date <= prev_month_end)
	)
	prev_cost = prev_result.scalar() or 0

	# Cost change
	change = ((current_cost - prev_cost) / prev_cost * 100) if prev_cost > 0 else 0

	# Latest usage
	latest_usage = await db.execute(
		select(UsageDailyORM)
		.order_by(UsageDailyORM.usage_date.desc())
		.limit(1)
	)
	usage = latest_usage.scalar_one_or_none()

	# Alerts
	alert_result = await db.execute(
		select(
			func.count(UsageAlertORM.id).filter(UsageAlertORM.status == AlertStatus.ACTIVE),
			func.count(UsageAlertORM.id).filter(UsageAlertORM.status == AlertStatus.TRIGGERED),
		)
	)
	active_alerts, triggered_alerts = alert_result.one()

	# Invoices
	invoice_result = await db.execute(
		select(
			func.count(InvoiceORM.id).filter(InvoiceORM.status == InvoiceStatus.PENDING),
			func.count(InvoiceORM.id).filter(InvoiceORM.status == InvoiceStatus.OVERDUE),
		)
	)
	pending_invoices, overdue_invoices = invoice_result.one()

	# Cost by service (from cost_breakdown)
	cost_by_service = {}

	# Daily costs for chart
	daily_result = await db.execute(
		select(UsageDailyORM)
		.where(UsageDailyORM.usage_date >= month_start)
		.order_by(UsageDailyORM.usage_date)
	)
	daily_records = daily_result.scalars().all()
	daily_costs = [
		{
			"date": r.usage_date.isoformat(),
			"cost_cents": r.cost_total_cents,
			"storage_cents": r.storage_cost_cents,
			"transfer_cents": r.transfer_cost_cents,
		}
		for r in daily_records
	]

	return BillingDashboard(
		current_month_cost_cents=current_cost,
		previous_month_cost_cents=prev_cost,
		cost_change_percentage=change,
		current_storage_bytes=usage.storage_bytes if usage else 0,
		storage_limit_bytes=None,
		current_transfer_bytes=usage.transfer_out_bytes if usage else 0,
		transfer_limit_bytes=None,
		active_alerts=active_alerts,
		triggered_alerts=triggered_alerts,
		pending_invoices=pending_invoices,
		overdue_invoices=overdue_invoices,
		cost_by_service=cost_by_service,
		daily_costs=daily_costs,
	)


@router.post("/estimate", response_model=CostEstimate)
async def estimate_costs(
	storage_gb: Decimal = Query(..., gt=0),
	transfer_gb: Decimal = Query(..., ge=0),
	documents: int = Query(..., ge=0),
	users: int = Query(..., ge=1),
	db: Annotated[AsyncSession, Depends(get_db)] = None,
	user: Annotated[User, Depends(get_current_user)] = None,
):
	"""Estimate monthly costs based on projected usage."""
	calculator = CostCalculator(db)
	estimated = await calculator.estimate_monthly_cost(
		storage_gb=storage_gb,
		transfer_gb=transfer_gb,
		documents=documents,
		users=users,
	)

	return CostEstimate(
		storage_gb=storage_gb,
		transfer_gb=transfer_gb,
		documents=documents,
		users=users,
		estimated_monthly_cost_cents=estimated,
		breakdown=[],
	)


# ============ Usage ============

@router.get("/usage", response_model=list[UsageDaily])
async def get_usage(
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
	start_date: date = Query(default=None),
	end_date: date = Query(default=None),
	limit: int = 30,
):
	"""Get daily usage records."""
	if not start_date:
		start_date = date.today() - timedelta(days=limit)
	if not end_date:
		end_date = date.today()

	result = await db.execute(
		select(UsageDailyORM)
		.where(UsageDailyORM.usage_date >= start_date)
		.where(UsageDailyORM.usage_date <= end_date)
		.order_by(UsageDailyORM.usage_date.desc())
		.limit(limit)
	)
	return result.scalars().all()


@router.get("/usage/summary", response_model=UsageSummary)
async def get_usage_summary(
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
	start_date: date = Query(...),
	end_date: date = Query(...),
):
	"""Get aggregated usage summary for a period."""
	result = await db.execute(
		select(
			func.sum(UsageDailyORM.storage_bytes),
			func.sum(UsageDailyORM.transfer_in_bytes),
			func.sum(UsageDailyORM.transfer_out_bytes),
			func.max(UsageDailyORM.documents_count),
			func.sum(UsageDailyORM.pages_processed),
			func.sum(UsageDailyORM.api_calls),
			func.max(UsageDailyORM.active_users),
			func.sum(UsageDailyORM.cost_total_cents),
		)
		.where(UsageDailyORM.usage_date >= start_date)
		.where(UsageDailyORM.usage_date <= end_date)
	)
	row = result.one()
	days = (end_date - start_date).days + 1

	return UsageSummary(
		start_date=start_date,
		end_date=end_date,
		total_storage_bytes=row[0] or 0,
		total_transfer_in_bytes=row[1] or 0,
		total_transfer_out_bytes=row[2] or 0,
		total_documents=row[3] or 0,
		total_pages_processed=row[4] or 0,
		total_api_calls=row[5] or 0,
		peak_active_users=row[6] or 0,
		total_cost_cents=row[7] or 0,
		daily_average_cost_cents=(row[7] or 0) // days if days > 0 else 0,
	)


# ============ Alerts ============

@router.get("/alerts", response_model=list[UsageAlert])
async def list_alerts(
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
	status_filter: AlertStatus | None = Query(None, alias="status"),
):
	"""List usage alerts."""
	query = select(UsageAlertORM)
	if status_filter:
		query = query.where(UsageAlertORM.status == status_filter)
	query = query.order_by(UsageAlertORM.created_at.desc())

	result = await db.execute(query)
	return result.scalars().all()


@router.post("/alerts", response_model=UsageAlert, status_code=status.HTTP_201_CREATED)
async def create_alert(
	data: UsageAlertCreate,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
	tenant_id: UUID | None = None,
):
	"""Create a new usage alert."""
	manager = UsageAlertManager(db)
	alert = await manager.create_alert(
		tenant_id=tenant_id or user.id,  # Use user ID as fallback
		**data.model_dump(),
	)
	return alert


@router.patch("/alerts/{alert_id}", response_model=UsageAlert)
async def update_alert(
	alert_id: str,
	data: UsageAlertUpdate,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Update an alert."""
	result = await db.execute(
		select(UsageAlertORM).where(UsageAlertORM.id == alert_id)
	)
	alert = result.scalar_one_or_none()
	if not alert:
		raise HTTPException(status_code=404, detail="Alert not found")

	update_data = data.model_dump(exclude_unset=True)
	for key, value in update_data.items():
		setattr(alert, key, value)

	alert.updated_at = datetime.utcnow()
	await db.commit()
	await db.refresh(alert)
	return alert


@router.delete("/alerts/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(
	alert_id: str,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Delete an alert."""
	result = await db.execute(
		select(UsageAlertORM).where(UsageAlertORM.id == alert_id)
	)
	alert = result.scalar_one_or_none()
	if not alert:
		raise HTTPException(status_code=404, detail="Alert not found")

	await db.delete(alert)
	await db.commit()


@router.post("/alerts/check")
async def check_alerts(
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
	tenant_id: UUID | None = None,
):
	"""Manually check all alerts and trigger notifications."""
	manager = UsageAlertManager(db)
	notifications = await manager.check_alerts(tenant_id or user.id)
	return {"notifications": notifications}


# ============ Invoices ============

@router.get("/invoices", response_model=list[InvoiceSummary])
async def list_invoices(
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
	status_filter: InvoiceStatus | None = Query(None, alias="status"),
	skip: int = 0,
	limit: int = 50,
):
	"""List invoices."""
	query = select(InvoiceORM)
	if status_filter:
		query = query.where(InvoiceORM.status == status_filter)
	query = query.order_by(InvoiceORM.created_at.desc())
	query = query.offset(skip).limit(limit)

	result = await db.execute(query)
	return result.scalars().all()


@router.get("/invoices/{invoice_id}", response_model=Invoice)
async def get_invoice(
	invoice_id: str,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Get invoice details."""
	result = await db.execute(
		select(InvoiceORM).where(InvoiceORM.id == invoice_id)
	)
	invoice = result.scalar_one_or_none()
	if not invoice:
		raise HTTPException(status_code=404, detail="Invoice not found")
	return invoice


@router.post("/invoices", response_model=Invoice, status_code=status.HTTP_201_CREATED)
async def create_invoice(
	data: InvoiceCreate,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
	tenant_id: UUID | None = None,
):
	"""Create a new invoice."""
	# Generate invoice number
	now = datetime.utcnow()
	count_result = await db.execute(
		select(func.count(InvoiceORM.id))
		.where(InvoiceORM.created_at >= now.replace(month=1, day=1))
	)
	count = count_result.scalar() or 0
	invoice_number = f"INV-{now.year}-{count + 1:05d}"

	invoice = InvoiceORM(
		id=uuid7str(),
		tenant_id=tenant_id or user.id,
		invoice_number=invoice_number,
		**data.model_dump(exclude={"line_items"}),
	)

	# Calculate totals from line items
	subtotal = 0
	for i, item_data in enumerate(data.line_items):
		item_subtotal = int(item_data.quantity * item_data.unit_price_cents)
		item_tax = int(item_subtotal * item_data.tax_rate / 100)
		item_total = item_subtotal - item_data.discount_cents + item_tax

		item = InvoiceLineItemORM(
			id=uuid7str(),
			invoice_id=invoice.id,
			line_number=i + 1,
			subtotal_cents=item_subtotal,
			tax_cents=item_tax,
			total_cents=item_total,
			**item_data.model_dump(),
		)
		db.add(item)
		subtotal += item_total

	invoice.subtotal_cents = subtotal
	invoice.total_cents = subtotal
	invoice.balance_due_cents = subtotal

	db.add(invoice)
	await db.commit()
	await db.refresh(invoice)
	return invoice


@router.patch("/invoices/{invoice_id}", response_model=Invoice)
async def update_invoice(
	invoice_id: str,
	data: InvoiceUpdate,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Update an invoice."""
	result = await db.execute(
		select(InvoiceORM).where(InvoiceORM.id == invoice_id)
	)
	invoice = result.scalar_one_or_none()
	if not invoice:
		raise HTTPException(status_code=404, detail="Invoice not found")

	update_data = data.model_dump(exclude_unset=True)
	for key, value in update_data.items():
		setattr(invoice, key, value)

	invoice.updated_at = datetime.utcnow()
	await db.commit()
	await db.refresh(invoice)
	return invoice
