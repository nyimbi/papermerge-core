# (c) Copyright Datacraft, 2026
"""Email delivery for scheduled analytics reports.

Sends a plain-text email with the report file attached.
SMTP configuration is read from env vars (same keys as EmailService):
  PM_SMTP_HOST   — defaults to 217.76.53.144
  PM_SMTP_PORT   — defaults to 587
  PM_SMTP_USER   — optional; omit for unauthenticated relay
  PM_SMTP_PASSWORD — optional
  PM_SMTP_FROM   — defaults to reports@darchiva.io
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

_log = logging.getLogger(__name__)

_REPORT_TYPE_LABELS: dict[str, str] = {
	"document_summary": "Document Summary",
	"ocr_quality": "OCR Quality",
	"scanning_productivity": "Scanning Productivity",
	"expiry_upcoming": "Expiry Upcoming",
}


def _body_text(report_name: str, report_type: str, filename: str) -> str:
	label = _REPORT_TYPE_LABELS.get(report_type, report_type.replace("_", " ").title())
	return (
		f"Hello,\n\n"
		f"Please find attached your scheduled dArchiva report.\n\n"
		f"Report name : {report_name}\n"
		f"Report type : {label}\n"
		f"Attachment  : {filename}\n\n"
		f"This report was generated automatically by dArchiva.\n"
		f"To manage your scheduled reports, log in and visit Reports > Scheduled Reports.\n\n"
		f"-- dArchiva Document Management\n"
	)


async def send_report_email(
	recipients: list[str],
	report_name: str,
	file_bytes: bytes,
	filename: str,
	report_type: str,
) -> None:
	"""
	Send *file_bytes* as an email attachment to every address in *recipients*.

	Uses STARTTLS; no auth if PM_SMTP_USER/PASSWORD are unset (relay mode).
	Raises smtplib.SMTPException or OSError on failure — let the caller handle retry.
	"""
	import asyncio

	loop = asyncio.get_event_loop()
	await loop.run_in_executor(
		None,
		_send_sync,
		recipients,
		report_name,
		file_bytes,
		filename,
		report_type,
	)


def _send_sync(
	recipients: list[str],
	report_name: str,
	file_bytes: bytes,
	filename: str,
	report_type: str,
) -> None:
	host = os.environ.get("PM_SMTP_HOST", "217.76.53.144")
	port = int(os.environ.get("PM_SMTP_PORT", "587"))
	user = os.environ.get("PM_SMTP_USER", "")
	password = os.environ.get("PM_SMTP_PASSWORD", "")
	from_addr = os.environ.get("PM_SMTP_FROM", "reports@darchiva.io")

	if not host:
		_log.warning("scheduled_reports: PM_SMTP_HOST not set — skipping email delivery")
		return

	subject = f"dArchiva Scheduled Report: {report_name}"
	body = _body_text(report_name, report_type, filename)

	# Determine MIME subtype from filename extension
	mime_subtype = "vnd.openxmlformats-officedocument.spreadsheetml.sheet" if filename.endswith(".xlsx") else "csv"

	errors: list[str] = []
	ctx = ssl.create_default_context()

	try:
		with smtplib.SMTP(host, port, timeout=20) as smtp:
			smtp.ehlo()
			smtp.starttls(context=ctx)
			smtp.ehlo()
			if user and password:
				smtp.login(user, password)

			for to_addr in recipients:
				msg = MIMEMultipart()
				msg["Subject"] = subject
				msg["From"] = from_addr
				msg["To"] = to_addr
				msg.attach(MIMEText(body, "plain", "utf-8"))

				attachment = MIMEApplication(file_bytes, _subtype=mime_subtype)
				attachment.add_header(
					"Content-Disposition",
					"attachment",
					filename=filename,
				)
				msg.attach(attachment)

				try:
					smtp.sendmail(from_addr, [to_addr], msg.as_bytes())
					_log.info(
						"scheduled_reports: sent '%s' → %s",
						report_name, to_addr,
					)
				except smtplib.SMTPException as exc:
					_log.error(
						"scheduled_reports: failed to send to %s: %s",
						to_addr, exc,
					)
					errors.append(to_addr)

	except OSError as exc:
		_log.error(
			"scheduled_reports: SMTP connection error (%s:%s): %s",
			host, port, exc,
		)
		raise

	if errors:
		_log.warning(
			"scheduled_reports: delivery failed for %d recipient(s): %s",
			len(errors), errors,
		)
