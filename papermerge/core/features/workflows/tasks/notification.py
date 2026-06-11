# (c) Copyright Datacraft, 2026
"""Notification tasks for workflow engine."""
import logging
from typing import Any
from uuid import UUID

from prefect import task

from papermerge.core.config.prefect import get_prefect_settings
from .base import TaskResult, log_task_start, log_task_complete

logger = logging.getLogger(__name__)
settings = get_prefect_settings()


@task(
	name="notify",
	description="Send notification via email or webhook",
	retries=settings.default_retries,
	retry_delay_seconds=settings.retry_delay_seconds,
)
async def notify_task(ctx: dict, config: dict) -> dict:
	"""
	Send notifications about workflow events.

	Notification channels:
	- email: Send email to users/groups
	- webhook: POST to external URL
	- in_app: Create in-app notification

	Config options:
		- channel: str - Notification channel (email/webhook/in_app)
		- recipients: list[str] - User IDs or email addresses
		- template: str - Notification template name
		- subject: str - Email subject
		- message: str - Notification message
		- webhook_url: str - Webhook endpoint URL
		- include_document_link: bool - Include link to document

	Returns:
		Notification status
	"""
	log_task_start("notify", ctx, config)

	document_id = ctx["document_id"]
	channel = config.get("channel", "email")
	recipients = config.get("recipients", [])
	template = config.get("template")
	subject = config.get("subject", "Workflow Notification")
	message = config.get("message", "")
	webhook_url = config.get("webhook_url")
	include_document_link = config.get("include_document_link", True)

	try:
		notification_result = {
			"document_id": document_id,
			"channel": channel,
			"recipients": recipients,
			"sent": False,
			"delivery_status": [],
		}

		# Build notification context
		notify_context = {
			"document_id": document_id,
			"workflow_id": ctx.get("workflow_id"),
			"instance_id": ctx.get("instance_id"),
		}

		# Add document link if requested
		if include_document_link:
			import os
			base_url = os.environ.get("APP_BASE_URL", "http://localhost")
			notify_context["document_url"] = f"{base_url}/documents/{document_id}"

		# Add previous step results for template variables
		for step_type, step_result in ctx.get("previous_results", {}).items():
			notify_context[step_type] = step_result.get("data", {})

		if channel == "email":
			# Send email notification
			notification_result = await _send_email_notification(
				recipients=recipients,
				subject=subject,
				message=message,
				template=template,
				context=notify_context,
			)

		elif channel == "webhook":
			# Send webhook notification
			notification_result = await _send_webhook_notification(
				webhook_url=webhook_url,
				context=notify_context,
				config=config,
			)

		elif channel == "in_app":
			# Create in-app notification
			notification_result = await _create_in_app_notification(
				recipients=recipients,
				message=message,
				context=notify_context,
			)

		result = TaskResult.success_result(
			f"Notification sent via {channel}",
			notification=notification_result,
		)
		log_task_complete("notify", ctx, result)
		return result.model_dump()

	except Exception as e:
		logger.exception(f"Notification failed for document {document_id}")
		result = TaskResult.failure_result(
			f"Notification failed: {str(e)}",
			error_code="NOTIFY_ERROR",
		)
		log_task_complete("notify", ctx, result)
		return result.model_dump()


async def _send_email_notification(
	recipients: list[str],
	subject: str,
	message: str,
	template: str | None,
	context: dict,
) -> dict:
	"""Send email via Stalwart (mail.lindela.io) using settings."""
	from papermerge.core.config.settings import get_settings
	cfg = get_settings()

	result: dict = {
		"channel": "email",
		"recipients": recipients,
		"sent": False,
		"delivery_status": [],
	}

	try:
		import smtplib
		import asyncio
		from email.mime.text import MIMEText
		from email.mime.multipart import MIMEMultipart
		from functools import partial

		host = cfg.smtp_host
		port = cfg.smtp_port
		user = cfg.smtp_user
		password = cfg.smtp_password
		from_addr = f"{cfg.smtp_from_name} <{cfg.smtp_from}>" if cfg.smtp_from_name else cfg.smtp_from
		use_tls = cfg.smtp_use_tls

		# Render body — substitute {{key}} placeholders from context
		body = message
		for key, value in context.items():
			if isinstance(value, str):
				body = body.replace(f"{{{{{key}}}}}", value)

		def _send_via_smtp(to_addrs: list[str]) -> list[dict]:
			statuses: list[dict] = []
			try:
				# Port 465 → implicit TLS (SMTP_SSL); all others → STARTTLS
				if port == 465:
					smtp_cls = smtplib.SMTP_SSL(host, port)
				else:
					smtp_cls = smtplib.SMTP(host, port)
					smtp_cls.ehlo()
					if use_tls:
						smtp_cls.starttls()
						smtp_cls.ehlo()

				with smtp_cls as smtp:
					if user and password:
						smtp.login(user, password)
					for recipient in to_addrs:
						msg = MIMEMultipart("alternative")
						msg["Subject"] = subject
						msg["From"] = from_addr
						msg["To"] = recipient
						msg.attach(MIMEText(body, "plain"))
						try:
							smtp.sendmail(cfg.smtp_from, [recipient], msg.as_string())
							statuses.append({"recipient": recipient, "status": "sent"})
						except smtplib.SMTPException as exc:
							statuses.append({"recipient": recipient, "status": "failed", "error": str(exc)})
			except smtplib.SMTPException as smtp_err:
				for recipient in to_addrs:
					statuses.append({"recipient": recipient, "status": "failed", "error": str(smtp_err)})
			return statuses

		loop = asyncio.get_event_loop()
		delivery_statuses = await loop.run_in_executor(None, partial(_send_via_smtp, recipients))
		result["delivery_status"] = delivery_statuses
		result["sent"] = any(s["status"] == "sent" for s in delivery_statuses)
		logger.info("Email sent for %d recipients via %s:%d", len(recipients), host, port)

	except Exception as e:
		logger.exception("Failed to send email notification")
		result["error"] = str(e)

	return result


async def _send_webhook_notification(
	webhook_url: str | None,
	context: dict,
	config: dict,
) -> dict:
	"""Send webhook notification."""
	result = {
		"channel": "webhook",
		"url": webhook_url,
		"sent": False,
		"response_code": None,
	}

	if not webhook_url:
		result["error"] = "No webhook URL configured"
		return result

	try:
		import httpx

		# Build payload
		payload = {
			"event": "workflow_notification",
			"timestamp": __import__("datetime").datetime.utcnow().isoformat(),
			"data": context,
		}

		# Add custom headers if configured
		headers = config.get("webhook_headers", {})
		headers.setdefault("Content-Type", "application/json")

		# Send webhook
		async with httpx.AsyncClient() as client:
			response = await client.post(
				webhook_url,
				json=payload,
				headers=headers,
				timeout=30.0,
			)

		result["response_code"] = response.status_code
		result["sent"] = response.status_code < 400

		if not result["sent"]:
			result["error"] = f"Webhook returned {response.status_code}"

		logger.info(f"Webhook notification sent to {webhook_url}: {response.status_code}")

	except Exception as e:
		logger.exception(f"Failed to send webhook notification to {webhook_url}")
		result["error"] = str(e)

	return result


async def _create_in_app_notification(
	recipients: list[str],
	message: str,
	context: dict,
) -> dict:
	"""Create in-app notification."""
	result = {
		"channel": "in_app",
		"recipients": recipients,
		"sent": False,
		"notification_ids": [],
	}

	try:
		import uuid
		from datetime import datetime, timezone
		from papermerge.core.db.engine import AsyncSessionLocal
		from papermerge.core.features.user_home.models import UserNotification

		document_id = context.get("document_id")
		workflow_id = context.get("workflow_id")
		document_url = context.get("document_url")

		title = f"Workflow notification for document {document_id}"
		notif_type = "workflow"
		metadata = {
			"workflow_id": workflow_id,
			"instance_id": context.get("instance_id"),
			"document_id": document_id,
		}

		async with AsyncSessionLocal() as db:
			for recipient in recipients:
				try:
					user_uuid = uuid.UUID(str(recipient))
				except (ValueError, AttributeError):
					logger.warning(f"Skipping invalid recipient UUID: {recipient!r}")
					continue

				notif = UserNotification(
					id=uuid.uuid4(),
					user_id=user_uuid,
					type=notif_type,
					title=title,
					message=message,
					is_read=False,
					link=document_url,
					notification_metadata=metadata,
					created_at=datetime.now(timezone.utc),
				)
				db.add(notif)
				result["notification_ids"].append(str(notif.id))

			await db.commit()

		result["sent"] = True
		logger.info(f"In-app notification created for {len(result['notification_ids'])} recipients")

	except Exception as e:
		logger.exception("Failed to create in-app notification")
		result["error"] = str(e)

	return result
