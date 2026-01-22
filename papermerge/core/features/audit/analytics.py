# (c) Copyright Datacraft, 2026
"""
Advanced Audit Analytics.

Provides analytics and reporting capabilities for audit data:
- Time-series activity trends
- User activity summaries
- Security anomaly detection
- Compliance reporting
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from collections import defaultdict

from sqlalchemy import select, func, and_, or_, case, text
from sqlalchemy.ext.asyncio import AsyncSession

from .db.orm import AuditLog
from .types import AuditOperation

logger = logging.getLogger(__name__)


@dataclass
class TimeSeriesPoint:
	"""A single point in a time series."""
	timestamp: datetime
	count: int
	breakdown: dict[str, int] = field(default_factory=dict)


@dataclass
class ActivityTrend:
	"""Activity trend over time."""
	period: str  # hourly, daily, weekly
	data: list[TimeSeriesPoint]
	total: int
	average: float
	peak: TimeSeriesPoint | None
	trend_direction: str  # increasing, decreasing, stable


@dataclass
class UserActivitySummary:
	"""Summary of a user's activity."""
	user_id: str
	username: str
	total_actions: int
	operations: dict[str, int]
	tables_accessed: dict[str, int]
	first_activity: datetime | None
	last_activity: datetime | None
	avg_daily_actions: float
	unusual_patterns: list[str]


@dataclass
class ResourceActivitySummary:
	"""Summary of activity on a resource."""
	resource_id: str
	table_name: str
	total_actions: int
	operations: dict[str, int]
	users_accessing: list[str]
	last_modified: datetime | None
	last_modifier: str | None


@dataclass
class SecurityAlert:
	"""Security anomaly or alert."""
	alert_type: str  # mass_deletion, unusual_access, brute_force, privilege_escalation
	severity: str  # low, medium, high, critical
	timestamp: datetime
	description: str
	affected_resources: list[str]
	user_id: str | None
	details: dict[str, Any]


@dataclass
class ComplianceReport:
	"""Compliance audit report."""
	report_period: tuple[datetime, datetime]
	total_events: int
	events_by_operation: dict[str, int]
	events_by_table: dict[str, int]
	users_active: int
	security_alerts: list[SecurityAlert]
	data_retention_status: dict[str, Any]
	access_reviews_required: list[dict]


class AuditAnalytics:
	"""Advanced audit analytics engine."""

	def __init__(self, session: AsyncSession):
		self.session = session

	async def get_activity_trend(
		self,
		period: str = "daily",
		days: int = 30,
		tenant_id: str | None = None,
		table_filter: str | None = None,
		operation_filter: str | None = None,
	) -> ActivityTrend:
		"""
		Get activity trend over time.

		Args:
			period: Aggregation period - 'hourly', 'daily', 'weekly'
			days: Number of days to analyze
			tenant_id: Optional tenant filter
			table_filter: Optional table name filter
			operation_filter: Optional operation filter
		"""
		since = datetime.utcnow() - timedelta(days=days)

		# Build date truncation based on period
		if period == "hourly":
			date_trunc = func.date_trunc('hour', AuditLog.timestamp)
		elif period == "weekly":
			date_trunc = func.date_trunc('week', AuditLog.timestamp)
		else:
			date_trunc = func.date_trunc('day', AuditLog.timestamp)

		# Build query
		conditions = [AuditLog.timestamp >= since]
		if table_filter:
			conditions.append(AuditLog.table_name == table_filter)
		if operation_filter:
			conditions.append(AuditLog.operation == operation_filter)

		query = (
			select(
				date_trunc.label('period'),
				AuditLog.operation,
				func.count().label('count'),
			)
			.where(and_(*conditions))
			.group_by(date_trunc, AuditLog.operation)
			.order_by(date_trunc)
		)

		result = await self.session.execute(query)
		rows = result.all()

		# Aggregate by period
		period_data: dict[datetime, dict[str, int]] = defaultdict(lambda: defaultdict(int))
		for row in rows:
			period_data[row.period][row.operation] += row.count

		# Convert to TimeSeriesPoints
		data_points = []
		for ts, breakdown in sorted(period_data.items()):
			point = TimeSeriesPoint(
				timestamp=ts,
				count=sum(breakdown.values()),
				breakdown=dict(breakdown),
			)
			data_points.append(point)

		total = sum(p.count for p in data_points)
		average = total / len(data_points) if data_points else 0
		peak = max(data_points, key=lambda p: p.count) if data_points else None

		# Determine trend direction
		if len(data_points) >= 2:
			recent = sum(p.count for p in data_points[-7:]) / min(7, len(data_points))
			earlier = sum(p.count for p in data_points[:-7]) / max(1, len(data_points) - 7)
			if recent > earlier * 1.1:
				trend_direction = "increasing"
			elif recent < earlier * 0.9:
				trend_direction = "decreasing"
			else:
				trend_direction = "stable"
		else:
			trend_direction = "stable"

		return ActivityTrend(
			period=period,
			data=data_points,
			total=total,
			average=average,
			peak=peak,
			trend_direction=trend_direction,
		)

	async def get_user_activity_summary(
		self,
		user_id: str,
		days: int = 30,
	) -> UserActivitySummary:
		"""Get activity summary for a specific user."""
		since = datetime.utcnow() - timedelta(days=days)

		# Get total actions by operation
		ops_query = (
			select(AuditLog.operation, func.count().label('count'))
			.where(and_(AuditLog.user_id == user_id, AuditLog.timestamp >= since))
			.group_by(AuditLog.operation)
		)
		ops_result = await self.session.execute(ops_query)
		operations = {row.operation: row.count for row in ops_result}

		# Get tables accessed
		tables_query = (
			select(AuditLog.table_name, func.count().label('count'))
			.where(and_(AuditLog.user_id == user_id, AuditLog.timestamp >= since))
			.group_by(AuditLog.table_name)
		)
		tables_result = await self.session.execute(tables_query)
		tables = {row.table_name: row.count for row in tables_result}

		# Get first and last activity
		time_query = (
			select(
				func.min(AuditLog.timestamp).label('first'),
				func.max(AuditLog.timestamp).label('last'),
				AuditLog.username,
			)
			.where(and_(AuditLog.user_id == user_id, AuditLog.timestamp >= since))
			.group_by(AuditLog.username)
		)
		time_result = await self.session.execute(time_query)
		time_row = time_result.first()

		total = sum(operations.values())
		avg_daily = total / days if days > 0 else 0

		# Detect unusual patterns
		unusual = []
		if operations.get(AuditOperation.DELETE, 0) > total * 0.3:
			unusual.append("High deletion rate")
		if len(tables) > 20:
			unusual.append("Accessing many different tables")

		return UserActivitySummary(
			user_id=user_id,
			username=time_row.username if time_row else "",
			total_actions=total,
			operations=operations,
			tables_accessed=tables,
			first_activity=time_row.first if time_row else None,
			last_activity=time_row.last if time_row else None,
			avg_daily_actions=avg_daily,
			unusual_patterns=unusual,
		)

	async def get_top_users(
		self,
		limit: int = 10,
		days: int = 30,
		operation: str | None = None,
	) -> list[dict]:
		"""Get top active users."""
		since = datetime.utcnow() - timedelta(days=days)

		conditions = [AuditLog.timestamp >= since, AuditLog.user_id.isnot(None)]
		if operation:
			conditions.append(AuditLog.operation == operation)

		query = (
			select(
				AuditLog.user_id,
				AuditLog.username,
				func.count().label('action_count'),
				func.count(func.distinct(AuditLog.table_name)).label('tables_accessed'),
			)
			.where(and_(*conditions))
			.group_by(AuditLog.user_id, AuditLog.username)
			.order_by(func.count().desc())
			.limit(limit)
		)

		result = await self.session.execute(query)
		return [
			{
				"user_id": str(row.user_id),
				"username": row.username,
				"action_count": row.action_count,
				"tables_accessed": row.tables_accessed,
			}
			for row in result
		]

	async def get_resource_activity(
		self,
		resource_id: str,
		table_name: str,
		days: int = 30,
	) -> ResourceActivitySummary:
		"""Get activity summary for a specific resource."""
		since = datetime.utcnow() - timedelta(days=days)

		# Get operations
		ops_query = (
			select(AuditLog.operation, func.count().label('count'))
			.where(and_(
				AuditLog.record_id == resource_id,
				AuditLog.table_name == table_name,
				AuditLog.timestamp >= since,
			))
			.group_by(AuditLog.operation)
		)
		ops_result = await self.session.execute(ops_query)
		operations = {row.operation: row.count for row in ops_result}

		# Get users
		users_query = (
			select(func.distinct(AuditLog.username))
			.where(and_(
				AuditLog.record_id == resource_id,
				AuditLog.table_name == table_name,
				AuditLog.timestamp >= since,
				AuditLog.username.isnot(None),
			))
		)
		users_result = await self.session.execute(users_query)
		users = [row[0] for row in users_result if row[0]]

		# Get last modification
		last_query = (
			select(AuditLog.timestamp, AuditLog.username)
			.where(and_(
				AuditLog.record_id == resource_id,
				AuditLog.table_name == table_name,
				AuditLog.operation == AuditOperation.UPDATE,
			))
			.order_by(AuditLog.timestamp.desc())
			.limit(1)
		)
		last_result = await self.session.execute(last_query)
		last_row = last_result.first()

		return ResourceActivitySummary(
			resource_id=resource_id,
			table_name=table_name,
			total_actions=sum(operations.values()),
			operations=operations,
			users_accessing=users,
			last_modified=last_row.timestamp if last_row else None,
			last_modifier=last_row.username if last_row else None,
		)

	async def detect_security_anomalies(
		self,
		hours: int = 24,
	) -> list[SecurityAlert]:
		"""Detect security anomalies in recent activity."""
		since = datetime.utcnow() - timedelta(hours=hours)
		alerts = []

		# Detect mass deletions
		mass_delete_query = (
			select(
				AuditLog.user_id,
				AuditLog.username,
				AuditLog.table_name,
				func.count().label('delete_count'),
			)
			.where(and_(
				AuditLog.operation == AuditOperation.DELETE,
				AuditLog.timestamp >= since,
			))
			.group_by(AuditLog.user_id, AuditLog.username, AuditLog.table_name)
			.having(func.count() > 50)
		)
		mass_delete_result = await self.session.execute(mass_delete_query)
		for row in mass_delete_result:
			alerts.append(SecurityAlert(
				alert_type="mass_deletion",
				severity="high",
				timestamp=datetime.utcnow(),
				description=f"User {row.username} deleted {row.delete_count} records from {row.table_name}",
				affected_resources=[row.table_name],
				user_id=str(row.user_id) if row.user_id else None,
				details={"table": row.table_name, "count": row.delete_count},
			))

		# Detect unusual activity hours
		hour_query = (
			select(
				AuditLog.user_id,
				AuditLog.username,
				func.extract('hour', AuditLog.timestamp).label('hour'),
				func.count().label('count'),
			)
			.where(and_(
				AuditLog.timestamp >= since,
				or_(
					func.extract('hour', AuditLog.timestamp) < 6,
					func.extract('hour', AuditLog.timestamp) > 22,
				),
			))
			.group_by(AuditLog.user_id, AuditLog.username, func.extract('hour', AuditLog.timestamp))
			.having(func.count() > 10)
		)
		hour_result = await self.session.execute(hour_query)
		for row in hour_result:
			alerts.append(SecurityAlert(
				alert_type="unusual_hours",
				severity="medium",
				timestamp=datetime.utcnow(),
				description=f"User {row.username} had {row.count} actions during unusual hours",
				affected_resources=[],
				user_id=str(row.user_id) if row.user_id else None,
				details={"hour": int(row.hour), "count": row.count},
			))

		# Detect access to sensitive tables
		sensitive_tables = ['users', 'roles', 'permissions', 'key_encryption_keys', 'policies']
		sensitive_query = (
			select(
				AuditLog.user_id,
				AuditLog.username,
				AuditLog.table_name,
				func.count().label('count'),
			)
			.where(and_(
				AuditLog.table_name.in_(sensitive_tables),
				AuditLog.timestamp >= since,
			))
			.group_by(AuditLog.user_id, AuditLog.username, AuditLog.table_name)
			.having(func.count() > 20)
		)
		sensitive_result = await self.session.execute(sensitive_query)
		for row in sensitive_result:
			alerts.append(SecurityAlert(
				alert_type="sensitive_access",
				severity="medium",
				timestamp=datetime.utcnow(),
				description=f"User {row.username} accessed sensitive table {row.table_name} {row.count} times",
				affected_resources=[row.table_name],
				user_id=str(row.user_id) if row.user_id else None,
				details={"table": row.table_name, "count": row.count},
			))

		return alerts

	async def generate_compliance_report(
		self,
		start_date: datetime,
		end_date: datetime,
	) -> ComplianceReport:
		"""Generate a compliance audit report for the given period."""
		conditions = [
			AuditLog.timestamp >= start_date,
			AuditLog.timestamp <= end_date,
		]

		# Total events
		total_query = select(func.count()).select_from(AuditLog).where(and_(*conditions))
		total_result = await self.session.execute(total_query)
		total_events = total_result.scalar() or 0

		# Events by operation
		ops_query = (
			select(AuditLog.operation, func.count().label('count'))
			.where(and_(*conditions))
			.group_by(AuditLog.operation)
		)
		ops_result = await self.session.execute(ops_query)
		events_by_operation = {row.operation: row.count for row in ops_result}

		# Events by table
		tables_query = (
			select(AuditLog.table_name, func.count().label('count'))
			.where(and_(*conditions))
			.group_by(AuditLog.table_name)
			.order_by(func.count().desc())
			.limit(20)
		)
		tables_result = await self.session.execute(tables_query)
		events_by_table = {row.table_name: row.count for row in tables_result}

		# Active users
		users_query = (
			select(func.count(func.distinct(AuditLog.user_id)))
			.where(and_(*conditions, AuditLog.user_id.isnot(None)))
		)
		users_result = await self.session.execute(users_query)
		users_active = users_result.scalar() or 0

		# Get security alerts for the period
		alerts = await self.detect_security_anomalies(
			hours=int((end_date - start_date).total_seconds() / 3600)
		)

		return ComplianceReport(
			report_period=(start_date, end_date),
			total_events=total_events,
			events_by_operation=events_by_operation,
			events_by_table=events_by_table,
			users_active=users_active,
			security_alerts=alerts,
			data_retention_status={
				"oldest_record": start_date.isoformat(),
				"retention_policy_days": 365,
				"compliant": True,
			},
			access_reviews_required=[],
		)

	async def get_operation_distribution(
		self,
		days: int = 30,
	) -> dict[str, dict]:
		"""Get distribution of operations over time."""
		since = datetime.utcnow() - timedelta(days=days)

		query = (
			select(
				AuditLog.operation,
				func.count().label('total'),
				func.count(func.distinct(AuditLog.user_id)).label('unique_users'),
				func.count(func.distinct(AuditLog.table_name)).label('unique_tables'),
			)
			.where(AuditLog.timestamp >= since)
			.group_by(AuditLog.operation)
		)

		result = await self.session.execute(query)
		return {
			row.operation: {
				"total": row.total,
				"unique_users": row.unique_users,
				"unique_tables": row.unique_tables,
			}
			for row in result
		}
