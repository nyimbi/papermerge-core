# (c) Copyright Datacraft, 2026
"""Celery task for dispatching outbound notification emails."""
from __future__ import annotations

import logging

from celery import shared_task

_log = logging.getLogger(__name__)


@shared_task(
	bind=True,
	max_retries=3,
	default_retry_delay=60,
	name="darchiva.notifications.send_email",
)
def send_email_notification(self, to: str, subject: str, html_body: str) -> dict:
	"""
	Send an HTML email via SMTP.

	Args:
		to: recipient address
		subject: email subject line
		html_body: rendered HTML string

	Returns a dict: {ok: bool, to: str}.
	Retries up to 3 times on SMTP/network failure with 60 s backoff.
	"""
	from papermerge.core.features.email_notifications.service import EmailService

	_log.info("send_email_notification: → %s [%s]", to, subject)
	try:
		EmailService().send_sync(to, subject, html_body)
		return {"ok": True, "to": to}
	except Exception as exc:
		_log.warning(
			"send_email_notification: failed (attempt %d/%d) to=%s: %s",
			self.request.retries + 1, self.max_retries, to, exc,
		)
		raise self.retry(exc=exc)
