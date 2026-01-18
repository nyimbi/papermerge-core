# (c) Copyright Datacraft, 2026
"""
Usage alert management.
"""
import json
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_extensions import uuid7str

from papermerge.core.logging import get_logger
from papermerge.core.config import get_settings

from .db.orm import UsageAlert, AlertType, AlertStatus, UsageDaily

if TYPE_CHECKING:
	from uuid import UUID

logger = get_logger(__name__)
settings = get_settings()


class UsageAlertManager:
	"""
	Manage usage alerts and notifications.
	"""

	def __init__(self, db: AsyncSession):
		self.db = db

	async def create_alert(
		self,
		tenant_id: "UUID",
		alert_type: AlertType,
		name: str,
		threshold_value: Decimal,
		threshold_unit: str,
		notify_at_percentage: list[int] | None = None,
		notification_channels: list[str] | None = None,
		description: str | None = None,
	) -> UsageAlert:
		"""Create a new usage alert."""
		alert = UsageAlert(
			id=uuid7str(),
			tenant_id=tenant_id,
			alert_type=alert_type,
			name=name,
			description=description,
			threshold_value=threshold_value,
			threshold_unit=threshold_unit,
			notify_at_percentage=notify_at_percentage or [50, 75, 90, 100],
			notification_channels=notification_channels or ["email"],
		)

		self.db.add(alert)
		await self.db.commit()
		await self.db.refresh(alert)
		return alert

	async def check_alerts(self, tenant_id: "UUID") -> list[dict]:
		"""
		Check all active alerts for a tenant and trigger notifications.

		Returns:
			List of triggered alert notifications
		"""
		# Get active alerts
		result = await self.db.execute(
			select(UsageAlert)
			.where(UsageAlert.tenant_id == tenant_id)
			.where(UsageAlert.status == AlertStatus.ACTIVE)
		)
		alerts = result.scalars().all()

		notifications = []

		for alert in alerts:
			# Get current value based on alert type
			current_value = await self._get_current_value(tenant_id, alert.alert_type)

			# Update alert with current value
			alert.current_value = current_value
			alert.percentage_used = (
				(current_value / alert.threshold_value * 100)
				if alert.threshold_value > 0
				else Decimal("0")
			)

			# Check if any notification thresholds are crossed
			for threshold in alert.notify_at_percentage:
				if (
					alert.percentage_used >= threshold
					and threshold not in alert.notifications_sent
				):
					# Trigger notification
					notification = await self._trigger_notification(alert, threshold)
					notifications.append(notification)

					# Mark as sent
					alert.notifications_sent = list(alert.notifications_sent) + [threshold]

					# Update status if at or over 100%
					if threshold >= 100:
						alert.status = AlertStatus.TRIGGERED
						alert.last_triggered_at = datetime.utcnow()
						alert.triggered_count += 1

		await self.db.commit()
		return notifications

	async def _get_current_value(
		self,
		tenant_id: "UUID",
		alert_type: AlertType,
	) -> Decimal:
		"""Get current value for an alert type."""
		# Get latest usage record
		result = await self.db.execute(
			select(UsageDaily)
			.where(UsageDaily.tenant_id == tenant_id)
			.order_by(UsageDaily.usage_date.desc())
			.limit(1)
		)
		usage = result.scalar_one_or_none()

		if not usage:
			return Decimal("0")

		if alert_type == AlertType.STORAGE_THRESHOLD:
			# Return storage in GB
			return Decimal(usage.storage_bytes) / (1024 ** 3)
		elif alert_type == AlertType.TRANSFER_THRESHOLD:
			# Return transfer out in GB (monthly cumulative)
			month_start = usage.usage_date.replace(day=1)
			total_result = await self.db.execute(
				select(func.sum(UsageDaily.transfer_out_bytes))
				.where(UsageDaily.tenant_id == tenant_id)
				.where(UsageDaily.usage_date >= month_start)
			)
			total = total_result.scalar() or 0
			return Decimal(total) / (1024 ** 3)
		elif alert_type == AlertType.COST_THRESHOLD:
			# Return monthly cost in dollars
			month_start = usage.usage_date.replace(day=1)
			total_result = await self.db.execute(
				select(func.sum(UsageDaily.cost_total_cents))
				.where(UsageDaily.tenant_id == tenant_id)
				.where(UsageDaily.usage_date >= month_start)
			)
			total = total_result.scalar() or 0
			return Decimal(total) / 100
		elif alert_type == AlertType.DOCUMENT_LIMIT:
			return Decimal(usage.documents_count)
		elif alert_type == AlertType.USER_LIMIT:
			return Decimal(usage.active_users)
		else:
			return Decimal("0")

	async def _trigger_notification(
		self,
		alert: UsageAlert,
		threshold: int,
	) -> dict:
		"""Trigger notification for an alert."""
		notification = {
			"alert_id": alert.id,
			"alert_name": alert.name,
			"alert_type": alert.alert_type.value,
			"threshold_percentage": threshold,
			"current_value": float(alert.current_value),
			"threshold_value": float(alert.threshold_value),
			"percentage_used": float(alert.percentage_used),
			"threshold_unit": alert.threshold_unit,
			"channels": alert.notification_channels,
			"triggered_at": datetime.utcnow().isoformat(),
		}

		logger.info(
			f"Alert triggered: {alert.name} at {threshold}% "
			f"({alert.current_value}/{alert.threshold_value} {alert.threshold_unit})"
		)

		# Send notifications via configured channels
		for channel in alert.notification_channels:
			if channel == "email":
				await self._send_email_notification(alert, threshold)
			elif channel == "webhook":
				await self._send_webhook_notification(alert, threshold)
			elif channel == "slack":
				await self._send_slack_notification(alert, threshold)

		return notification

	async def _send_email_notification(
		self,
		alert: UsageAlert,
		threshold: int,
	) -> None:
		"""Send email notification via configured SMTP or email service."""
		from papermerge.core.features.tenants.db.orm import Tenant

		# Get tenant billing email
		result = await self.db.execute(
			select(Tenant).where(Tenant.id == alert.tenant_id)
		)
		tenant = result.scalar_one_or_none()

		if not tenant or not tenant.billing_email:
			logger.warning(f"No billing email configured for tenant {alert.tenant_id}")
			return

		subject = f"Usage Alert: {alert.name} at {threshold}%"
		body = self._format_alert_message(alert, threshold)

		# Use configured SMTP or email service
		smtp_host = getattr(settings, 'smtp_host', None)
		smtp_port = getattr(settings, 'smtp_port', 587)
		smtp_user = getattr(settings, 'smtp_user', None)
		smtp_password = getattr(settings, 'smtp_password', None)
		smtp_from = getattr(settings, 'smtp_from_address', 'noreply@darchiva.local')

		if smtp_host and smtp_user:
			import smtplib
			from email.mime.text import MIMEText
			from email.mime.multipart import MIMEMultipart

			try:
				msg = MIMEMultipart('alternative')
				msg['Subject'] = subject
				msg['From'] = smtp_from
				msg['To'] = tenant.billing_email

				text_part = MIMEText(body, 'plain')
				msg.attach(text_part)

				with smtplib.SMTP(smtp_host, smtp_port) as server:
					server.starttls()
					if smtp_password:
						server.login(smtp_user, smtp_password)
					server.sendmail(smtp_from, [tenant.billing_email], msg.as_string())

				logger.info(f"Email notification sent for alert {alert.id} to {tenant.billing_email}")
			except Exception as e:
				logger.error(f"Failed to send email notification for alert {alert.id}: {e}")
		else:
			# Log for pickup by email worker when SMTP is not configured
			logger.info(
				f"Email notification queued for alert {alert.id}: "
				f"to={tenant.billing_email}, subject={subject}"
			)

	async def _send_webhook_notification(
		self,
		alert: UsageAlert,
		threshold: int,
	) -> None:
		"""Send webhook notification to configured URL."""
		from papermerge.core.features.tenants.db.orm import Tenant

		# Get tenant webhook configuration from features JSONB
		result = await self.db.execute(
			select(Tenant).where(Tenant.id == alert.tenant_id)
		)
		tenant = result.scalar_one_or_none()

		webhook_url = (
			tenant.features.get('alert_webhook_url')
			if tenant and tenant.features
			else None
		)

		if not webhook_url:
			logger.debug(f"No webhook URL configured for tenant {alert.tenant_id}")
			return

		payload = {
			"event": "usage_alert",
			"alert_id": alert.id,
			"alert_name": alert.name,
			"alert_type": alert.alert_type.value,
			"threshold_percentage": threshold,
			"current_value": float(alert.current_value),
			"threshold_value": float(alert.threshold_value),
			"percentage_used": float(alert.percentage_used),
			"threshold_unit": alert.threshold_unit,
			"tenant_id": str(alert.tenant_id),
			"triggered_at": datetime.utcnow().isoformat(),
		}

		try:
			async with httpx.AsyncClient(timeout=30.0) as client:
				response = await client.post(
					webhook_url,
					json=payload,
					headers={"Content-Type": "application/json"},
				)
				response.raise_for_status()
				logger.info(f"Webhook notification sent for alert {alert.id}")
		except httpx.HTTPError as e:
			logger.error(f"Failed to send webhook notification for alert {alert.id}: {e}")

	async def _send_slack_notification(
		self,
		alert: UsageAlert,
		threshold: int,
	) -> None:
		"""Send Slack notification via webhook."""
		from papermerge.core.features.tenants.db.orm import Tenant

		# Get tenant Slack webhook from features JSONB
		result = await self.db.execute(
			select(Tenant).where(Tenant.id == alert.tenant_id)
		)
		tenant = result.scalar_one_or_none()

		slack_webhook_url = (
			tenant.features.get('slack_webhook_url')
			if tenant and tenant.features
			else None
		)

		if not slack_webhook_url:
			logger.debug(f"No Slack webhook configured for tenant {alert.tenant_id}")
			return

		# Format Slack message with blocks
		color = "#ff0000" if threshold >= 100 else "#ffa500" if threshold >= 75 else "#36a64f"

		message = {
			"attachments": [
				{
					"color": color,
					"blocks": [
						{
							"type": "header",
							"text": {
								"type": "plain_text",
								"text": f"Usage Alert: {alert.name}",
								"emoji": True,
							}
						},
						{
							"type": "section",
							"fields": [
								{
									"type": "mrkdwn",
									"text": f"*Type:*\n{alert.alert_type.value.replace('_', ' ').title()}"
								},
								{
									"type": "mrkdwn",
									"text": f"*Threshold:*\n{threshold}%"
								},
								{
									"type": "mrkdwn",
									"text": f"*Current:*\n{alert.current_value:.2f} {alert.threshold_unit}"
								},
								{
									"type": "mrkdwn",
									"text": f"*Limit:*\n{alert.threshold_value:.2f} {alert.threshold_unit}"
								},
							]
						},
						{
							"type": "context",
							"elements": [
								{
									"type": "mrkdwn",
									"text": f"Triggered at {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
								}
							]
						}
					]
				}
			]
		}

		try:
			async with httpx.AsyncClient(timeout=30.0) as client:
				response = await client.post(
					slack_webhook_url,
					json=message,
					headers={"Content-Type": "application/json"},
				)
				response.raise_for_status()
				logger.info(f"Slack notification sent for alert {alert.id}")
		except httpx.HTTPError as e:
			logger.error(f"Failed to send Slack notification for alert {alert.id}: {e}")

	def _format_alert_message(self, alert: UsageAlert, threshold: int) -> str:
		"""Format alert message for email."""
		return f"""Usage Alert: {alert.name}

Your usage has reached {threshold}% of the configured threshold.

Alert Details:
- Type: {alert.alert_type.value.replace('_', ' ').title()}
- Current Usage: {alert.current_value:.2f} {alert.threshold_unit}
- Threshold: {alert.threshold_value:.2f} {alert.threshold_unit}
- Usage Percentage: {alert.percentage_used:.1f}%

{"ACTION REQUIRED: You have exceeded your configured limit." if threshold >= 100 else "Please review your usage to avoid service interruption."}

This is an automated notification from dArchiva.
"""

	async def resolve_alert(self, alert_id: str) -> UsageAlert | None:
		"""Mark an alert as resolved."""
		result = await self.db.execute(
			select(UsageAlert).where(UsageAlert.id == alert_id)
		)
		alert = result.scalar_one_or_none()

		if alert:
			alert.status = AlertStatus.RESOLVED
			alert.notifications_sent = []  # Reset for next cycle
			await self.db.commit()
			await self.db.refresh(alert)

		return alert

	async def reset_alert(self, alert_id: str) -> UsageAlert | None:
		"""Reset an alert to active status."""
		result = await self.db.execute(
			select(UsageAlert).where(UsageAlert.id == alert_id)
		)
		alert = result.scalar_one_or_none()

		if alert:
			alert.status = AlertStatus.ACTIVE
			alert.notifications_sent = []
			await self.db.commit()
			await self.db.refresh(alert)

		return alert
