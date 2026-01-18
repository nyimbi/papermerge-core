# (c) Copyright Datacraft, 2026
"""
Linode Object Storage cost collector.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

import httpx

from papermerge.core.logging import get_logger

from .base import CostCollector, UsageMetrics, CostBreakdown

logger = get_logger(__name__)


class LinodeCostCollector(CostCollector):
	"""
	Collect cost and usage data from Linode Object Storage.
	"""

	API_BASE = "https://api.linode.com/v4"

	def __init__(
		self,
		credentials: dict,
		config: dict | None = None,
	):
		"""
		Initialize Linode collector.

		Args:
			credentials: Dict with 'access_key', 'secret_key', and 'api_token'
			config: Dict with 'cluster_id', 'bucket_name', etc.
		"""
		super().__init__(credentials, config)

		self.api_token = credentials.get("api_token")
		self.cluster_id = config.get("cluster_id", "us-east-1") if config else "us-east-1"
		self.bucket_name = config.get("bucket_name") if config else None

		# Linode pricing (as of 2024)
		# $5/month for 250GB storage + 1TB transfer
		# $0.02/GB/month for additional storage
		# $0.01/GB for additional transfer
		self.base_storage_gb = 250
		self.base_transfer_gb = 1000
		self.base_cost_cents = 500  # $5/month
		self.extra_storage_per_gb_cents = 2  # $0.02/GB
		self.extra_transfer_per_gb_cents = 1  # $0.01/GB

	@property
	def _headers(self) -> dict:
		return {
			"Authorization": f"Bearer {self.api_token}",
			"Content-Type": "application/json",
		}

	async def validate_credentials(self) -> bool:
		"""Validate Linode credentials."""
		try:
			async with httpx.AsyncClient() as client:
				response = await client.get(
					f"{self.API_BASE}/account",
					headers=self._headers,
				)
				return response.status_code == 200
		except Exception as e:
			logger.error(f"Linode credential validation failed: {e}")
			return False

	async def get_current_storage(self) -> int:
		"""Get current Object Storage usage in bytes."""
		try:
			async with httpx.AsyncClient() as client:
				# Get all buckets
				response = await client.get(
					f"{self.API_BASE}/object-storage/buckets/{self.cluster_id}",
					headers=self._headers,
				)

				if response.status_code != 200:
					return 0

				data = response.json()
				total_bytes = 0

				for bucket in data.get("data", []):
					if self.bucket_name and bucket["label"] != self.bucket_name:
						continue
					total_bytes += bucket.get("size", 0)

				return total_bytes
		except Exception as e:
			logger.error(f"Failed to get Linode storage size: {e}")
			return 0

	async def get_usage(
		self,
		start_date: date,
		end_date: date,
	) -> list[UsageMetrics]:
		"""
		Get Linode usage metrics.

		Note: Linode doesn't provide daily granularity for object storage,
		so we estimate based on current usage.
		"""
		metrics = []

		try:
			# Get current storage
			current_storage = await self.get_current_storage()

			# Get transfer stats
			transfer = await self._get_transfer_stats()

			# Distribute across date range (simplified)
			days = (end_date - start_date).days + 1
			daily_transfer_out = transfer.get("out", 0) // days
			daily_transfer_in = transfer.get("in", 0) // days

			current = start_date
			while current <= end_date:
				metrics.append(UsageMetrics(
					date=current,
					storage_bytes=current_storage,
					transfer_in_bytes=daily_transfer_in,
					transfer_out_bytes=daily_transfer_out,
				))
				current += timedelta(days=1)

		except Exception as e:
			logger.error(f"Failed to get Linode usage: {e}")

		return metrics

	async def _get_transfer_stats(self) -> dict:
		"""Get transfer statistics for the current billing period."""
		try:
			async with httpx.AsyncClient() as client:
				response = await client.get(
					f"{self.API_BASE}/account/transfer",
					headers=self._headers,
				)

				if response.status_code != 200:
					return {"in": 0, "out": 0}

				data = response.json()
				return {
					"in": data.get("used", 0),
					"out": data.get("used", 0),  # Linode combines in/out
					"quota": data.get("quota", 0),
				}
		except Exception:
			return {"in": 0, "out": 0}

	async def get_costs(
		self,
		start_date: date,
		end_date: date,
	) -> list[CostBreakdown]:
		"""
		Calculate costs based on Linode's pricing model.

		Linode charges flat rate for base tier, then per-GB for overages.
		"""
		costs = []

		try:
			current_storage_bytes = await self.get_current_storage()
			transfer = await self._get_transfer_stats()

			# Calculate monthly costs
			storage_gb = current_storage_bytes / (1024 ** 3)
			transfer_gb = transfer.get("out", 0) / (1024 ** 3)

			# Base tier covers 250GB storage + 1TB transfer
			storage_overage_gb = max(0, storage_gb - self.base_storage_gb)
			transfer_overage_gb = max(0, transfer_gb - self.base_transfer_gb)

			# Calculate costs
			storage_cost = int(storage_overage_gb * self.extra_storage_per_gb_cents)
			transfer_cost = int(transfer_overage_gb * self.extra_transfer_per_gb_cents)

			# Add base cost (prorated if partial month)
			days = (end_date - start_date).days + 1
			days_in_month = 30  # Approximate
			prorated_base = int(self.base_cost_cents * (days / days_in_month))

			# Distribute costs across days
			daily_storage = (storage_cost + prorated_base) // days
			daily_transfer = transfer_cost // days

			current = start_date
			while current <= end_date:
				costs.append(CostBreakdown(
					date=current,
					storage_cost_cents=daily_storage,
					transfer_cost_cents=daily_transfer,
					total_cost_cents=daily_storage + daily_transfer,
					details={
						"storage_gb": round(storage_gb, 2),
						"transfer_gb": round(transfer_gb, 2),
						"storage_overage_gb": round(storage_overage_gb, 2),
						"transfer_overage_gb": round(transfer_overage_gb, 2),
					},
				))
				current += timedelta(days=1)

		except Exception as e:
			logger.error(f"Failed to calculate Linode costs: {e}")

		return costs

	async def get_invoices(self) -> list[dict]:
		"""Get Linode invoices."""
		try:
			async with httpx.AsyncClient() as client:
				response = await client.get(
					f"{self.API_BASE}/account/invoices",
					headers=self._headers,
				)

				if response.status_code != 200:
					return []

				return response.json().get("data", [])
		except Exception as e:
			logger.error(f"Failed to get Linode invoices: {e}")
			return []
