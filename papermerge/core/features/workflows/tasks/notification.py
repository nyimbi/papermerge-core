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
			# TODO: Get proper base URL from settings
			notify_context["document_url"] = f"/documents/{document_id}"

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
	"""Send email notification."""
	result = {
		"channel": "email",
		"recipients": recipients,
		"sent": False,
		"delivery_status": [],
	}

	try:
		# TODO: Integrate with email service
		# For now, simulate email sending
		for recipient in recipients:
			# Would actually send email here
			result["delivery_status"].append({
				"recipient": recipient,
				"status": "queued",
				"message_id": None,
			})

		result["sent"] = True
		logger.info(f"Email notification queued for {len(recipients)} recipients")

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
		# TODO: Integrate with notification service
		# Would create notification records in database
		for recipient in recipients:
			# Simulated notification creation
			result["notification_ids"].append(f"notif_{recipient}_{context.get('document_id')}")

		result["sent"] = True
		logger.info(f"In-app notification created for {len(recipients)} recipients")

	except Exception as e:
		logger.exception("Failed to create in-app notification")
		result["error"] = str(e)

	return result
