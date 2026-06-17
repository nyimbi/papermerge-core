# (c) Copyright Datacraft, 2026
"""Email notification service — SMTP send + HTML templates."""
from __future__ import annotations

import asyncio
import logging
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# EmailService
# ---------------------------------------------------------------------------

class EmailService:
	"""Thin SMTP client driven entirely by env vars."""

	def __init__(self) -> None:
		self.host: str = os.environ.get("PM_SMTP_HOST", "")
		self.port: int = int(os.environ.get("PM_SMTP_PORT", "587"))
		self.user: str = os.environ.get("PM_SMTP_USER", "")
		self.password: str = os.environ.get("PM_SMTP_PASSWORD", "")
		self.from_addr: str = os.environ.get("PM_SMTP_FROM", self.user)

	# ------------------------------------------------------------------
	# Internal sync send (runs in executor or directly from Celery worker)
	# ------------------------------------------------------------------

	def _build_message(self, to: str, subject: str, html_body: str) -> MIMEMultipart:
		msg = MIMEMultipart("alternative")
		msg["Subject"] = subject
		msg["From"] = self.from_addr
		msg["To"] = to
		msg.attach(MIMEText(html_body, "html", "utf-8"))
		return msg

	def send_sync(self, to: str, subject: str, html_body: str) -> None:
		"""Blocking send — safe to call from a Celery task."""
		if not self.host:
			_log.warning("email_notifications: PM_SMTP_HOST not configured, skipping send to %s", to)
			return

		msg = self._build_message(to, subject, html_body)
		ctx = ssl.create_default_context()
		try:
			with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
				smtp.ehlo()
				smtp.starttls(context=ctx)
				smtp.ehlo()
				if self.user and self.password:
					smtp.login(self.user, self.password)
				smtp.sendmail(self.from_addr, [to], msg.as_bytes())
			_log.info("email_notifications: sent '%s' → %s", subject, to)
		except smtplib.SMTPAuthenticationError as exc:
			_log.error("email_notifications: auth failed for %s: %s", self.user, exc)
			raise
		except smtplib.SMTPException as exc:
			_log.error("email_notifications: SMTP error sending to %s: %s", to, exc)
			raise
		except OSError as exc:
			_log.error("email_notifications: connection error (%s:%s): %s", self.host, self.port, exc)
			raise

	async def send(self, to: str, subject: str, html_body: str) -> None:
		"""Async wrapper — runs send_sync in the default executor."""
		loop = asyncio.get_event_loop()
		await loop.run_in_executor(None, self.send_sync, to, subject, html_body)


# ---------------------------------------------------------------------------
# HTML templates
# ---------------------------------------------------------------------------

_BASE_STYLE = """
	body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
	        background: #0f172a; color: #e2e8f0; margin: 0; padding: 0; }}
	.wrapper {{ max-width: 600px; margin: 32px auto; background: #1e293b;
	            border-radius: 8px; overflow: hidden; }}
	.header {{ padding: 24px 32px; }}
	.content {{ padding: 24px 32px; }}
	.footer {{ padding: 16px 32px; font-size: 12px; color: #64748b;
	           border-top: 1px solid #334155; }}
	table {{ border-collapse: collapse; width: 100%; }}
	th, td {{ text-align: left; padding: 8px 12px; border-bottom: 1px solid #334155; }}
	th {{ background: #0f172a; color: #94a3b8; font-size: 12px; text-transform: uppercase; }}
	.badge {{ display: inline-block; padding: 2px 10px; border-radius: 9999px;
	          font-size: 12px; font-weight: 600; }}
	.badge-amber {{ background: #78350f; color: #fcd34d; }}
	.badge-red   {{ background: #7f1d1d; color: #fca5a5; }}
	.badge-green {{ background: #14532d; color: #86efac; }}
"""


def batch_complete(
	batch_name: str,
	page_count: int,
	scan_date: str,
	project_name: str,
) -> str:
	"""HTML email: batch scanning complete."""
	return f"""<!DOCTYPE html><html><head><style>{_BASE_STYLE}</style></head><body>
<div class="wrapper">
  <div class="header" style="background:#1e3a5f;">
    <h1 style="margin:0;font-size:20px;color:#60a5fa;">
      Batch Complete
    </h1>
  </div>
  <div class="content">
    <p>Batch <strong>{batch_name}</strong> in project
       <strong>{project_name}</strong> has been scanned successfully.</p>
    <table>
      <tr><th>Field</th><th>Value</th></tr>
      <tr><td>Pages scanned</td><td>{page_count}</td></tr>
      <tr><td>Scan date</td><td>{scan_date}</td></tr>
      <tr><td>Project</td><td>{project_name}</td></tr>
    </table>
  </div>
  <div class="footer">dArchiva &mdash; Document Management System</div>
</div>
</body></html>"""


def sla_breach(
	project_name: str,
	batch_name: str,
	deadline: str,
	breach_type: str,
) -> str:
	"""HTML email: SLA breach warning or critical."""
	is_critical = breach_type.lower() == "critical"
	header_bg = "#7f1d1d" if is_critical else "#78350f"
	header_color = "#fca5a5" if is_critical else "#fcd34d"
	badge_cls = "badge-red" if is_critical else "badge-amber"
	label = breach_type.upper()
	return f"""<!DOCTYPE html><html><head><style>{_BASE_STYLE}</style></head><body>
<div class="wrapper">
  <div class="header" style="background:{header_bg};">
    <h1 style="margin:0;font-size:20px;color:{header_color};">
      SLA Breach &mdash; <span class="badge {badge_cls}">{label}</span>
    </h1>
  </div>
  <div class="content">
    <p>Project <strong>{project_name}</strong> has a
       <strong>{breach_type}</strong> SLA breach for batch
       <strong>{batch_name}</strong>.</p>
    <table>
      <tr><th>Field</th><th>Value</th></tr>
      <tr><td>Project</td><td>{project_name}</td></tr>
      <tr><td>Batch</td><td>{batch_name}</td></tr>
      <tr><td>Deadline</td><td>{deadline}</td></tr>
      <tr><td>Severity</td><td><span class="badge {badge_cls}">{label}</span></td></tr>
    </table>
    <p style="margin-top:16px;">Please take immediate action to resolve this breach.</p>
  </div>
  <div class="footer">dArchiva &mdash; Document Management System</div>
</div>
</body></html>"""


def exception_alert(
	exception_type: str,
	document_name: str,
	description: str,
) -> str:
	"""HTML email: processing exception raised."""
	return f"""<!DOCTYPE html><html><head><style>{_BASE_STYLE}</style></head><body>
<div class="wrapper">
  <div class="header" style="background:#422006;">
    <h1 style="margin:0;font-size:20px;color:#fb923c;">
      Exception Alert
    </h1>
  </div>
  <div class="content">
    <p>An exception has been raised during document processing.</p>
    <table>
      <tr><th>Field</th><th>Value</th></tr>
      <tr><td>Exception type</td>
          <td><span class="badge badge-amber">{exception_type}</span></td></tr>
      <tr><td>Document</td><td>{document_name}</td></tr>
      <tr><td>Description</td><td>{description}</td></tr>
    </table>
  </div>
  <div class="footer">dArchiva &mdash; Document Management System</div>
</div>
</body></html>"""


def weekly_kpi_summary(
	operator_name: str,
	pages_scanned: int,
	quality_rate: float,
	period: str,
) -> str:
	"""HTML email: weekly KPI digest for an operator."""
	quality_pct = f"{quality_rate:.1f}%"
	badge_cls = "badge-green" if quality_rate >= 90 else ("badge-amber" if quality_rate >= 70 else "badge-red")
	return f"""<!DOCTYPE html><html><head><style>{_BASE_STYLE}</style></head><body>
<div class="wrapper">
  <div class="header" style="background:#1e3a5f;">
    <h1 style="margin:0;font-size:20px;color:#60a5fa;">
      Weekly KPI Summary
    </h1>
  </div>
  <div class="content">
    <p>Hello <strong>{operator_name}</strong>, here is your performance summary
       for <strong>{period}</strong>.</p>
    <table>
      <tr><th>Metric</th><th>Value</th></tr>
      <tr><td>Pages scanned</td><td>{pages_scanned}</td></tr>
      <tr>
        <td>Quality rate</td>
        <td><span class="badge {badge_cls}">{quality_pct}</span></td>
      </tr>
      <tr><td>Period</td><td>{period}</td></tr>
    </table>
  </div>
  <div class="footer">dArchiva &mdash; Document Management System</div>
</div>
</body></html>"""
