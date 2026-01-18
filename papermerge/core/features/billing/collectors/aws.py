# (c) Copyright Datacraft, 2026
"""
AWS S3 cost collector.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from papermerge.core.logging import get_logger

from .base import CostCollector, UsageMetrics, CostBreakdown

logger = get_logger(__name__)

try:
	import boto3
	from botocore.exceptions import ClientError
	BOTO3_AVAILABLE = True
except ImportError:
	BOTO3_AVAILABLE = False


class AWSCostCollector(CostCollector):
	"""
	Collect cost and usage data from AWS S3 and Cost Explorer.
	"""

	def __init__(
		self,
		credentials: dict,
		config: dict | None = None,
	):
		"""
		Initialize AWS collector.

		Args:
			credentials: Dict with 'access_key_id' and 'secret_access_key'
			config: Dict with 'region', 'bucket_name', etc.
		"""
		super().__init__(credentials, config)

		if not BOTO3_AVAILABLE:
			raise RuntimeError("boto3 is not installed. Install with: pip install boto3")

		self.region = config.get("region", "us-east-1") if config else "us-east-1"
		self.bucket_name = config.get("bucket_name") if config else None

		self._s3_client = None
		self._ce_client = None
		self._cloudwatch_client = None

	@property
	def s3_client(self):
		if self._s3_client is None:
			self._s3_client = boto3.client(
				"s3",
				aws_access_key_id=self.credentials.get("access_key_id"),
				aws_secret_access_key=self.credentials.get("secret_access_key"),
				region_name=self.region,
			)
		return self._s3_client

	@property
	def ce_client(self):
		"""Cost Explorer client."""
		if self._ce_client is None:
			self._ce_client = boto3.client(
				"ce",
				aws_access_key_id=self.credentials.get("access_key_id"),
				aws_secret_access_key=self.credentials.get("secret_access_key"),
				region_name="us-east-1",  # Cost Explorer only available in us-east-1
			)
		return self._ce_client

	@property
	def cloudwatch_client(self):
		if self._cloudwatch_client is None:
			self._cloudwatch_client = boto3.client(
				"cloudwatch",
				aws_access_key_id=self.credentials.get("access_key_id"),
				aws_secret_access_key=self.credentials.get("secret_access_key"),
				region_name=self.region,
			)
		return self._cloudwatch_client

	async def validate_credentials(self) -> bool:
		"""Validate AWS credentials."""
		try:
			self.s3_client.list_buckets()
			return True
		except ClientError as e:
			logger.error(f"AWS credential validation failed: {e}")
			return False

	async def get_current_storage(self) -> int:
		"""Get current S3 storage usage in bytes."""
		if not self.bucket_name:
			return 0

		try:
			# Use CloudWatch metrics for bucket size
			response = self.cloudwatch_client.get_metric_statistics(
				Namespace="AWS/S3",
				MetricName="BucketSizeBytes",
				Dimensions=[
					{"Name": "BucketName", "Value": self.bucket_name},
					{"Name": "StorageType", "Value": "StandardStorage"},
				],
				StartTime=datetime.utcnow() - timedelta(days=2),
				EndTime=datetime.utcnow(),
				Period=86400,  # 1 day
				Statistics=["Average"],
			)

			if response["Datapoints"]:
				# Get most recent datapoint
				latest = max(response["Datapoints"], key=lambda x: x["Timestamp"])
				return int(latest["Average"])

			return 0
		except ClientError as e:
			logger.error(f"Failed to get S3 storage size: {e}")
			return 0

	async def get_usage(
		self,
		start_date: date,
		end_date: date,
	) -> list[UsageMetrics]:
		"""Get S3 usage metrics."""
		metrics = []

		if not self.bucket_name:
			return metrics

		try:
			current = start_date
			while current <= end_date:
				# Get storage metrics from CloudWatch
				storage = await self._get_storage_for_date(current)
				transfer = await self._get_transfer_for_date(current)

				metrics.append(UsageMetrics(
					date=current,
					storage_bytes=storage.get("total", 0),
					storage_hot_bytes=storage.get("standard", 0),
					storage_cold_bytes=storage.get("intelligent_tiering", 0),
					storage_archive_bytes=storage.get("glacier", 0),
					transfer_in_bytes=transfer.get("in", 0),
					transfer_out_bytes=transfer.get("out", 0),
					api_requests=transfer.get("requests", 0),
				))

				current += timedelta(days=1)

		except ClientError as e:
			logger.error(f"Failed to get AWS usage: {e}")

		return metrics

	async def _get_storage_for_date(self, target_date: date) -> dict:
		"""Get storage metrics for a specific date."""
		try:
			start = datetime.combine(target_date, datetime.min.time())
			end = start + timedelta(days=1)

			storage_types = [
				("StandardStorage", "standard"),
				("IntelligentTieringFAStorage", "intelligent_tiering"),
				("GlacierStorage", "glacier"),
			]

			result = {"total": 0}

			for storage_type, key in storage_types:
				response = self.cloudwatch_client.get_metric_statistics(
					Namespace="AWS/S3",
					MetricName="BucketSizeBytes",
					Dimensions=[
						{"Name": "BucketName", "Value": self.bucket_name},
						{"Name": "StorageType", "Value": storage_type},
					],
					StartTime=start,
					EndTime=end,
					Period=86400,
					Statistics=["Average"],
				)

				if response["Datapoints"]:
					value = int(response["Datapoints"][0]["Average"])
					result[key] = value
					result["total"] += value

			return result
		except ClientError:
			return {"total": 0}

	async def _get_transfer_for_date(self, target_date: date) -> dict:
		"""Get transfer metrics for a specific date."""
		try:
			start = datetime.combine(target_date, datetime.min.time())
			end = start + timedelta(days=1)

			result = {"in": 0, "out": 0, "requests": 0}

			# BytesDownloaded
			response = self.cloudwatch_client.get_metric_statistics(
				Namespace="AWS/S3",
				MetricName="BytesDownloaded",
				Dimensions=[
					{"Name": "BucketName", "Value": self.bucket_name},
				],
				StartTime=start,
				EndTime=end,
				Period=86400,
				Statistics=["Sum"],
			)
			if response["Datapoints"]:
				result["out"] = int(response["Datapoints"][0]["Sum"])

			# BytesUploaded
			response = self.cloudwatch_client.get_metric_statistics(
				Namespace="AWS/S3",
				MetricName="BytesUploaded",
				Dimensions=[
					{"Name": "BucketName", "Value": self.bucket_name},
				],
				StartTime=start,
				EndTime=end,
				Period=86400,
				Statistics=["Sum"],
			)
			if response["Datapoints"]:
				result["in"] = int(response["Datapoints"][0]["Sum"])

			return result
		except ClientError:
			return {"in": 0, "out": 0, "requests": 0}

	async def get_costs(
		self,
		start_date: date,
		end_date: date,
	) -> list[CostBreakdown]:
		"""Get cost breakdown from AWS Cost Explorer."""
		costs = []

		try:
			response = self.ce_client.get_cost_and_usage(
				TimePeriod={
					"Start": start_date.isoformat(),
					"End": (end_date + timedelta(days=1)).isoformat(),
				},
				Granularity="DAILY",
				Metrics=["UnblendedCost"],
				Filter={
					"Dimensions": {
						"Key": "SERVICE",
						"Values": ["Amazon Simple Storage Service"],
					}
				},
				GroupBy=[
					{"Type": "DIMENSION", "Key": "USAGE_TYPE"},
				],
			)

			# Process results by day
			for result in response.get("ResultsByTime", []):
				result_date = date.fromisoformat(result["TimePeriod"]["Start"])
				breakdown = CostBreakdown(date=result_date)

				for group in result.get("Groups", []):
					usage_type = group["Keys"][0]
					cost = Decimal(group["Metrics"]["UnblendedCost"]["Amount"])
					cost_cents = int(cost * 100)

					if "Storage" in usage_type or "TimedStorage" in usage_type:
						breakdown.storage_cost_cents += cost_cents
					elif "DataTransfer" in usage_type or "Bandwidth" in usage_type:
						breakdown.transfer_cost_cents += cost_cents
					else:
						breakdown.other_cost_cents += cost_cents

				breakdown.total_cost_cents = (
					breakdown.storage_cost_cents +
					breakdown.transfer_cost_cents +
					breakdown.other_cost_cents
				)
				costs.append(breakdown)

		except ClientError as e:
			logger.error(f"Failed to get AWS costs: {e}")

		return costs
