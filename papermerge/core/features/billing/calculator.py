# (c) Copyright Datacraft, 2026
"""
Cost calculation engine for billing.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.logging import get_logger

from .db.orm import PricingTier, ServiceType, UsageDaily

if TYPE_CHECKING:
	from uuid import UUID

logger = get_logger(__name__)


@dataclass
class CostLineItem:
	"""Individual cost line item."""
	service: ServiceType
	description: str
	quantity: Decimal
	unit_name: str
	unit_price_cents: int
	total_cents: int
	free_tier_applied: Decimal = Decimal("0")


@dataclass
class CostSummary:
	"""Summary of costs for a period."""
	start_date: date
	end_date: date
	line_items: list[CostLineItem]
	subtotal_cents: int
	discount_cents: int = 0
	tax_cents: int = 0
	total_cents: int = 0


class CostCalculator:
	"""
	Calculate costs based on usage and pricing tiers.
	"""

	def __init__(self, db: AsyncSession):
		self.db = db
		self._pricing_cache: dict[str, list[PricingTier]] = {}

	async def calculate_period_cost(
		self,
		tenant_id: "UUID",
		start_date: date,
		end_date: date,
		provider_id: str | None = None,
	) -> CostSummary:
		"""
		Calculate costs for a billing period.

		Args:
			tenant_id: Tenant ID
			start_date: Start of billing period
			end_date: End of billing period (inclusive)
			provider_id: Optional provider ID to use specific pricing

		Returns:
			CostSummary with line items and totals
		"""
		# Get usage data for period
		usage_result = await self.db.execute(
			select(UsageDaily)
			.where(UsageDaily.tenant_id == tenant_id)
			.where(UsageDaily.usage_date >= start_date)
			.where(UsageDaily.usage_date <= end_date)
		)
		usage_records = usage_result.scalars().all()

		# Aggregate usage
		total_storage_gb_days = Decimal("0")
		total_transfer_out_gb = Decimal("0")
		total_transfer_in_gb = Decimal("0")
		total_documents = 0
		total_pages = 0
		total_api_calls = 0
		total_search_queries = 0
		max_users = 0

		for usage in usage_records:
			# Storage is measured in GB-days
			total_storage_gb_days += Decimal(usage.storage_bytes) / (1024 ** 3)
			total_transfer_out_gb += Decimal(usage.transfer_out_bytes) / (1024 ** 3)
			total_transfer_in_gb += Decimal(usage.transfer_in_bytes) / (1024 ** 3)
			total_documents = max(total_documents, usage.documents_count)
			total_pages += usage.pages_processed
			total_api_calls += usage.api_calls
			total_search_queries += usage.search_queries
			max_users = max(max_users, usage.active_users)

		# Get pricing tiers
		pricing = await self._get_pricing(provider_id)

		# Calculate costs
		line_items = []

		# Storage cost (convert GB-days to GB-months)
		days = (end_date - start_date).days + 1
		storage_gb_months = total_storage_gb_days / Decimal(30)  # Approximate month
		storage_item = await self._calculate_tiered_cost(
			ServiceType.STORAGE,
			storage_gb_months,
			"GB-month",
			pricing,
			f"Storage ({storage_gb_months:.2f} GB-months)",
		)
		if storage_item:
			line_items.append(storage_item)

		# Transfer out cost
		transfer_item = await self._calculate_tiered_cost(
			ServiceType.TRANSFER_OUT,
			total_transfer_out_gb,
			"GB",
			pricing,
			f"Data Transfer Out ({total_transfer_out_gb:.2f} GB)",
		)
		if transfer_item:
			line_items.append(transfer_item)

		# OCR pages cost
		if total_pages > 0:
			ocr_item = await self._calculate_tiered_cost(
				ServiceType.OCR_PAGES,
				Decimal(total_pages),
				"pages",
				pricing,
				f"OCR Processing ({total_pages:,} pages)",
			)
			if ocr_item:
				line_items.append(ocr_item)

		# API calls cost
		if total_api_calls > 0:
			api_item = await self._calculate_tiered_cost(
				ServiceType.API_CALLS,
				Decimal(total_api_calls) / 1000,  # Price per 1000
				"1000 requests",
				pricing,
				f"API Calls ({total_api_calls:,} requests)",
			)
			if api_item:
				line_items.append(api_item)

		# Calculate totals
		subtotal = sum(item.total_cents for item in line_items)

		return CostSummary(
			start_date=start_date,
			end_date=end_date,
			line_items=line_items,
			subtotal_cents=subtotal,
			total_cents=subtotal,  # No discount or tax for now
		)

	async def _calculate_tiered_cost(
		self,
		service: ServiceType,
		quantity: Decimal,
		unit_name: str,
		pricing: dict[ServiceType, list[PricingTier]],
		description: str,
	) -> CostLineItem | None:
		"""Calculate cost for a service with tiered pricing."""
		tiers = pricing.get(service, [])
		if not tiers:
			return None

		total_cost = 0
		remaining = quantity
		free_applied = Decimal("0")

		# Sort tiers by min_units
		sorted_tiers = sorted(tiers, key=lambda t: t.min_units)

		for tier in sorted_tiers:
			if remaining <= 0:
				break

			# Apply free tier
			if tier.free_tier_units > 0 and free_applied < tier.free_tier_units:
				free_amount = min(
					remaining,
					Decimal(tier.free_tier_units) - free_applied
				)
				remaining -= free_amount
				free_applied += free_amount

			if remaining <= 0:
				break

			# Calculate tier capacity
			tier_capacity = (
				Decimal(tier.max_units - tier.min_units)
				if tier.max_units
				else remaining
			)

			# Calculate units in this tier
			units_in_tier = min(remaining, tier_capacity)
			tier_cost = int(units_in_tier * tier.unit_price_cents)
			total_cost += tier_cost
			remaining -= units_in_tier

		if quantity == 0 and free_applied == 0:
			return None

		return CostLineItem(
			service=service,
			description=description,
			quantity=quantity,
			unit_name=unit_name,
			unit_price_cents=int(tiers[0].unit_price_cents) if tiers else 0,
			total_cents=total_cost,
			free_tier_applied=free_applied,
		)

	async def _get_pricing(
		self,
		provider_id: str | None = None,
	) -> dict[ServiceType, list[PricingTier]]:
		"""Get pricing tiers, using cache if available."""
		cache_key = provider_id or "default"

		if cache_key in self._pricing_cache:
			return self._pricing_cache[cache_key]

		query = select(PricingTier).where(PricingTier.is_active == True)
		if provider_id:
			query = query.where(PricingTier.provider_id == provider_id)

		result = await self.db.execute(query)
		tiers = result.scalars().all()

		# Group by service
		pricing: dict[ServiceType, list[PricingTier]] = {}
		for tier in tiers:
			if tier.service not in pricing:
				pricing[tier.service] = []
			pricing[tier.service].append(tier)

		self._pricing_cache[cache_key] = pricing
		return pricing

	async def estimate_monthly_cost(
		self,
		storage_gb: Decimal,
		transfer_gb: Decimal,
		documents: int,
		users: int,
		provider_id: str | None = None,
	) -> int:
		"""
		Estimate monthly cost based on projected usage.

		Returns:
			Estimated cost in cents
		"""
		pricing = await self._get_pricing(provider_id)

		total = 0

		# Storage
		storage_item = await self._calculate_tiered_cost(
			ServiceType.STORAGE,
			storage_gb,
			"GB-month",
			pricing,
			"Storage",
		)
		if storage_item:
			total += storage_item.total_cents

		# Transfer
		transfer_item = await self._calculate_tiered_cost(
			ServiceType.TRANSFER_OUT,
			transfer_gb,
			"GB",
			pricing,
			"Transfer",
		)
		if transfer_item:
			total += transfer_item.total_cents

		return total
