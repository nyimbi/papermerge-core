# (c) Copyright Datacraft, 2026
"""
Email parser for MIME/EML files.

Parses email messages from various formats:
- Raw .eml files
- MIME multipart messages
- Outlook .msg files (with external library)
"""
import email
import hashlib
import logging
import re
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Any

from .views import ParsedEmail, ParsedAttachment

logger = logging.getLogger(__name__)


def _log_parse(message_id: str) -> str:
	return f"Parsing email: {message_id[:50]}..."


def _extract_address(addr_str: str) -> tuple[str, str | None]:
	"""Extract email address and name from address string."""
	name, address = parseaddr(addr_str)
	return address, name if name else None


def _extract_addresses(header_value: str | None) -> list[str]:
	"""Extract list of email addresses from header."""
	if not header_value:
		return []

	# Split on commas, accounting for quoted names
	addresses = []
	for part in re.split(r',(?=(?:[^"]*"[^"]*")*[^"]*$)', header_value):
		addr, _ = _extract_address(part.strip())
		if addr:
			addresses.append(addr)
	return addresses


def _parse_date(date_str: str | None) -> datetime | None:
	"""Parse email date header."""
	if not date_str:
		return None
	try:
		return parsedate_to_datetime(date_str)
	except (ValueError, TypeError):
		return None


def _get_body_text(msg: EmailMessage) -> str | None:
	"""Extract plain text body from message."""
	if msg.is_multipart():
		for part in msg.walk():
			content_type = part.get_content_type()
			content_disposition = str(part.get("Content-Disposition", ""))

			if content_type == "text/plain" and "attachment" not in content_disposition:
				payload = part.get_payload(decode=True)
				if payload:
					charset = part.get_content_charset() or "utf-8"
					try:
						return payload.decode(charset, errors="replace")
					except (LookupError, UnicodeDecodeError):
						return payload.decode("utf-8", errors="replace")
	else:
		if msg.get_content_type() == "text/plain":
			payload = msg.get_payload(decode=True)
			if payload:
				charset = msg.get_content_charset() or "utf-8"
				try:
					return payload.decode(charset, errors="replace")
				except (LookupError, UnicodeDecodeError):
					return payload.decode("utf-8", errors="replace")
	return None


def _get_body_html(msg: EmailMessage) -> str | None:
	"""Extract HTML body from message."""
	if msg.is_multipart():
		for part in msg.walk():
			content_type = part.get_content_type()
			content_disposition = str(part.get("Content-Disposition", ""))

			if content_type == "text/html" and "attachment" not in content_disposition:
				payload = part.get_payload(decode=True)
				if payload:
					charset = part.get_content_charset() or "utf-8"
					try:
						return payload.decode(charset, errors="replace")
					except (LookupError, UnicodeDecodeError):
						return payload.decode("utf-8", errors="replace")
	else:
		if msg.get_content_type() == "text/html":
			payload = msg.get_payload(decode=True)
			if payload:
				charset = msg.get_content_charset() or "utf-8"
				try:
					return payload.decode(charset, errors="replace")
				except (LookupError, UnicodeDecodeError):
					return payload.decode("utf-8", errors="replace")
	return None


def _extract_attachments(msg: EmailMessage, include_content: bool = True) -> list[ParsedAttachment]:
	"""Extract attachments from message."""
	attachments = []

	if not msg.is_multipart():
		return attachments

	for part in msg.walk():
		content_disposition = str(part.get("Content-Disposition", ""))
		content_type = part.get_content_type()

		# Skip text parts that are the body
		if content_type in ("text/plain", "text/html") and "attachment" not in content_disposition:
			continue

		# Skip multipart containers
		if content_type.startswith("multipart/"):
			continue

		# Check for attachment
		filename = part.get_filename()
		if not filename and "attachment" not in content_disposition:
			# Check for inline with Content-ID
			content_id = part.get("Content-ID")
			if not content_id:
				continue

		# Get content
		payload = part.get_payload(decode=True)
		if payload is None:
			continue

		# Generate filename if missing
		if not filename:
			content_id = part.get("Content-ID", "").strip("<>")
			ext = content_type.split("/")[-1] if "/" in content_type else "bin"
			filename = f"inline_{content_id or 'attachment'}.{ext}"

		# Determine if inline
		content_id = part.get("Content-ID")
		is_inline = bool(content_id) or "inline" in content_disposition

		attachment = ParsedAttachment(
			filename=filename,
			content_type=content_type,
			size_bytes=len(payload),
			content_id=content_id.strip("<>") if content_id else None,
			is_inline=is_inline,
			content=payload if include_content else None,
		)
		attachments.append(attachment)

	return attachments


def _extract_headers(msg: EmailMessage) -> dict[str, str]:
	"""Extract important headers as dict."""
	headers = {}
	important_headers = [
		"From", "To", "Cc", "Bcc", "Subject", "Date", "Message-ID",
		"In-Reply-To", "References", "Reply-To", "Content-Type",
		"X-Mailer", "X-Priority", "X-Spam-Status", "DKIM-Signature",
		"Received", "Return-Path",
	]

	for header in important_headers:
		value = msg.get(header)
		if value:
			# Handle multiple headers (like Received)
			if header in headers:
				if not isinstance(headers[header], list):
					headers[header] = [headers[header]]
				headers[header].append(str(value))
			else:
				headers[header] = str(value)

	return headers


class EmailParser:
	"""
	Parses email messages from various formats.

	Supports:
	- .eml files (RFC 5322)
	- Raw MIME content
	- Outlook .msg files (requires extract-msg)
	"""

	def __init__(self, include_attachments: bool = True):
		"""
		Initialize parser.

		Args:
			include_attachments: Whether to include attachment content in parsed result
		"""
		self.include_attachments = include_attachments

	def parse_bytes(self, content: bytes) -> ParsedEmail:
		"""Parse email from raw bytes."""
		msg = email.message_from_bytes(content, policy=policy.default)
		return self._parse_message(msg)

	def parse_string(self, content: str) -> ParsedEmail:
		"""Parse email from string."""
		msg = email.message_from_string(content, policy=policy.default)
		return self._parse_message(msg)

	def parse_file(self, path: Path | str) -> ParsedEmail:
		"""Parse email from file."""
		path = Path(path)

		if path.suffix.lower() == ".msg":
			return self._parse_msg_file(path)

		with open(path, "rb") as f:
			content = f.read()
		return self.parse_bytes(content)

	def _parse_message(self, msg: EmailMessage) -> ParsedEmail:
		"""Parse EmailMessage object."""
		message_id = msg.get("Message-ID", "")
		if message_id:
			message_id = message_id.strip("<>")
		else:
			# Generate a message ID if missing
			content = msg.as_bytes()
			message_id = hashlib.sha256(content).hexdigest()[:32] + "@generated"

		logger.info(_log_parse(message_id))

		from_addr, from_name = _extract_address(msg.get("From", ""))

		# Parse references
		references_str = msg.get("References", "")
		references = []
		if references_str:
			references = [ref.strip("<>") for ref in references_str.split()]

		in_reply_to = msg.get("In-Reply-To", "")
		if in_reply_to:
			in_reply_to = in_reply_to.strip("<>")

		return ParsedEmail(
			message_id=message_id,
			subject=msg.get("Subject"),
			from_address=from_addr,
			from_name=from_name,
			to_addresses=_extract_addresses(msg.get("To")),
			cc_addresses=_extract_addresses(msg.get("Cc")),
			bcc_addresses=_extract_addresses(msg.get("Bcc")),
			reply_to=msg.get("Reply-To"),
			in_reply_to=in_reply_to if in_reply_to else None,
			references=references,
			sent_date=_parse_date(msg.get("Date")),
			received_date=_parse_date(msg.get("Received")),
			body_text=_get_body_text(msg),
			body_html=_get_body_html(msg),
			headers=_extract_headers(msg),
			attachments=_extract_attachments(msg, self.include_attachments),
		)

	def _parse_msg_file(self, path: Path) -> ParsedEmail:
		"""Parse Outlook .msg file."""
		try:
			import extract_msg
		except ImportError:
			raise ImportError(
				"extract-msg package required for .msg files. "
				"Install with: pip install extract-msg"
			)

		msg = extract_msg.Message(str(path))

		message_id = msg.messageId or f"{hashlib.sha256(path.read_bytes()).hexdigest()[:32]}@generated"
		message_id = message_id.strip("<>")

		from_addr = msg.sender or ""
		from_name = msg.senderName

		# Build attachments
		attachments = []
		for att in msg.attachments:
			if hasattr(att, "data") and att.data:
				attachments.append(ParsedAttachment(
					filename=att.longFilename or att.shortFilename or "attachment",
					content_type=att.mimetype or "application/octet-stream",
					size_bytes=len(att.data),
					content_id=getattr(att, "contentId", None),
					is_inline=getattr(att, "isAttachment", True) is False,
					content=att.data if self.include_attachments else None,
				))

		return ParsedEmail(
			message_id=message_id,
			subject=msg.subject,
			from_address=from_addr,
			from_name=from_name,
			to_addresses=msg.to.split(";") if msg.to else [],
			cc_addresses=msg.cc.split(";") if msg.cc else [],
			bcc_addresses=msg.bcc.split(";") if msg.bcc else [],
			reply_to=msg.replyTo,
			in_reply_to=None,
			references=[],
			sent_date=msg.date,
			received_date=msg.receivedTime,
			body_text=msg.body,
			body_html=msg.htmlBody,
			headers={},
			attachments=attachments,
		)


# Convenience functions
def parse_email_file(path: Path | str, include_attachments: bool = True) -> ParsedEmail:
	"""Parse email from file path."""
	parser = EmailParser(include_attachments=include_attachments)
	return parser.parse_file(path)


def parse_email_bytes(content: bytes, include_attachments: bool = True) -> ParsedEmail:
	"""Parse email from raw bytes."""
	parser = EmailParser(include_attachments=include_attachments)
	return parser.parse_bytes(content)


def compute_thread_id(message_id: str, in_reply_to: str | None, references: list[str]) -> str:
	"""
	Compute thread ID from message headers.

	Uses References header if available, otherwise In-Reply-To,
	otherwise the message's own ID as thread root.
	"""
	if references:
		# First reference is typically the thread root
		return references[0]
	if in_reply_to:
		return in_reply_to
	return message_id
