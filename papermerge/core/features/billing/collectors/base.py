# (c) Copyright Datacraft, 2026
"""
Base class for cloud provider cost collectors.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass
class UsageMetrics:
	"""Usage metrics collected from a cloud provider."""
	date: date
	storage_bytes: int = 0
	storage_hot_bytes: int = 0
	storage_cold_bytes: int = 0
	storage_archive_bytes: int = 0
	transfer_in_bytes: int = 0
	transfer_out_bytes: int = 0
	api_requests: int = 0
	compute_hours: Decimal = Decimal("0")


@dataclass
class CostBreakdown:
	"""Cost breakdown from a cloud provider."""
	date: date
	storage_cost_cents: int = 0
	transfer_cost_cents: int = 0
	compute_cost_cents: int = 0
	other_cost_cents: int = 0
	total_cost_cents: int = 0
	details: dict | None = None


class CostCollector(ABC):
	"""
	Abstract base class for collecting cost and usage data
	from cloud providers.
	"""

	def __init__(
		self,
		credentials: dict,
		config: dict | None = None,
	):
		"""
		Initialize collector.

		Args:
			credentials: Provider-specific credentials
			config: Provider-specific configuration
		"""
		self.credentials = credentials
		self.config = config or {}

	@abstractmethod
	async def get_usage(
		self,
		start_date: date,
		end_date: date,
	) -> list[UsageMetrics]:
		"""
		Get usage metrics for a date range.

		Args:
			start_date: Start of the date range
			end_date: End of the date range (inclusive)

		Returns:
			List of UsageMetrics, one per day
		"""
		pass

	@abstractmethod
	async def get_costs(
		self,
		start_date: date,
		end_date: date,
	) -> list[CostBreakdown]:
		"""
		Get cost breakdown for a date range.

		Args:
			start_date: Start of the date range
			end_date: End of the date range (inclusive)

		Returns:
			List of CostBreakdown, one per day
		"""
		pass

	@abstractmethod
	async def validate_credentials(self) -> bool:
		"""
		Validate that the credentials are correct.

		Returns:
			True if credentials are valid
		"""
		pass

	@abstractmethod
	async def get_current_storage(self) -> int:
		"""
		Get current total storage usage in bytes.

		Returns:
			Storage usage in bytes
		"""
		pass
