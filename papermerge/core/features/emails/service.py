# (c) Copyright Datacraft, 2026
"""Email service layer for business logic."""
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from uuid_extensions import uuid7str

from .models import (
	EmailImportModel,
	EmailAttachmentModel,
	EmailThreadModel,
	EmailAccountModel,
	EmailRuleModel,
)
from .views import (
	ParsedEmail,
	ParsedAttachment,
	EmailImportCreate,
	EmailImportInfo,
	EmailImportListResponse,
	EmailAttachmentInfo,
	EmailThreadInfo,
	EmailThreadDetail,
	EmailThreadListResponse,
	EmailAccountCreate,
	EmailAccountUpdate,
	EmailAccountInfo,
	EmailAccountListResponse,
	EmailRuleCreate,
	EmailRuleUpdate,
	EmailRuleInfo,
	EmailRuleListResponse,
	EmailImportStatus,
	AttachmentStatus,
)
from .parser import compute_thread_id

logger = logging.getLogger(__name__)


def _log_import(message_id: str) -> str:
	return f"Importing email: {message_id[:40]}..."


# ----- Email Import -----

async def import_email(
	session: AsyncSession,
	parsed: ParsedEmail,
	options: EmailImportCreate,
	owner_id: str,
	attachment_documents: dict[str, str] | None = None,
) -> EmailImportModel:
	"""
	Import a parsed email into the system.

	Args:
		session: Database session
		parsed: Parsed email data
		options: Import options
		owner_id: User ID of the owner
		attachment_documents: Mapping of attachment filename to document ID

	Returns:
		Created EmailImportModel
	"""
	logger.info(_log_import(parsed.message_id))

	# Check for duplicate
	existing = await get_email_import_by_message_id(session, parsed.message_id)
	if existing:
		logger.warning(f"Email already imported: {parsed.message_id}")
		return existing

	# Get or create thread
	thread_model_id = None
	thread_id = compute_thread_id(parsed.message_id, parsed.in_reply_to, parsed.references)

	thread = await get_or_create_thread(
		session,
		thread_id=thread_id,
		subject=parsed.subject or "(no subject)",
		owner_id=owner_id,
		folder_id=options.folder_id,
	)
	if thread:
		thread_model_id = thread.id
		# Update thread metadata
		thread.message_count += 1
		if parsed.sent_date:
			if not thread.first_message_date or parsed.sent_date < thread.first_message_date:
				thread.first_message_date = parsed.sent_date
			if not thread.last_message_date or parsed.sent_date > thread.last_message_date:
				thread.last_message_date = parsed.sent_date

	# Create import record
	email_import = EmailImportModel(
		id=uuid7str(),
		message_id=parsed.message_id,
		thread_id=thread_model_id,
		subject=parsed.subject,
		from_address=parsed.from_address,
		from_name=parsed.from_name,
		to_addresses=parsed.to_addresses,
		cc_addresses=parsed.cc_addresses,
		bcc_addresses=parsed.bcc_addresses,
		reply_to=parsed.reply_to,
		in_reply_to=parsed.in_reply_to,
		references=parsed.references,
		body_text=parsed.body_text,
		body_html=parsed.body_html,
		has_attachments=len(parsed.attachments) > 0,
		attachment_count=len(parsed.attachments),
		sent_date=parsed.sent_date,
		received_date=parsed.received_date,
		source=options.source.value,
		source_account_id=options.source_account_id,
		raw_headers=parsed.headers,
		import_status=EmailImportStatus.PROCESSING.value,
		owner_id=owner_id,
		folder_id=options.folder_id,
	)
	session.add(email_import)

	# Import attachments
	attachment_documents = attachment_documents or {}
	for att in parsed.attachments:
		# Check filter
		if options.attachment_filter and not _matches_filter(att.content_type, options.attachment_filter):
			continue

		att_model = EmailAttachmentModel(
			id=uuid7str(),
			email_import_id=email_import.id,
			document_id=attachment_documents.get(att.filename),
			filename=att.filename,
			content_type=att.content_type,
			size_bytes=att.size_bytes,
			content_id=att.content_id,
			is_inline=att.is_inline,
			import_status=AttachmentStatus.PENDING.value if options.import_attachments else AttachmentStatus.SKIPPED.value,
		)
		session.add(att_model)

	email_import.import_status = EmailImportStatus.COMPLETED.value
	await session.commit()
	await session.refresh(email_import)

	return email_import


def _matches_filter(content_type: str, filter_patterns: list[str]) -> bool:
	"""Check if content type matches any filter pattern."""
	for pattern in filter_patterns:
		if pattern == content_type:
			return True
		if pattern.endswith("/*"):
			prefix = pattern[:-2]
			if content_type.startswith(prefix + "/"):
				return True
	return False


async def get_email_import(
	session: AsyncSession,
	import_id: str,
) -> EmailImportModel | None:
	"""Get email import by ID."""
	stmt = select(EmailImportModel).where(
		EmailImportModel.id == import_id
	).options(selectinload(EmailImportModel.attachments))
	result = await session.execute(stmt)
	return result.scalar_one_or_none()


async def get_email_import_by_message_id(
	session: AsyncSession,
	message_id: str,
) -> EmailImportModel | None:
	"""Get email import by message ID."""
	stmt = select(EmailImportModel).where(
		EmailImportModel.message_id == message_id
	)
	result = await session.execute(stmt)
	return result.scalar_one_or_none()


async def list_email_imports(
	session: AsyncSession,
	owner_id: str,
	page: int = 1,
	page_size: int = 50,
	folder_id: str | None = None,
	thread_id: str | None = None,
	search: str | None = None,
	source: str | None = None,
) -> EmailImportListResponse:
	"""List email imports with pagination and filters."""
	base_query = select(EmailImportModel).where(
		EmailImportModel.owner_id == owner_id
	)

	if folder_id:
		base_query = base_query.where(EmailImportModel.folder_id == folder_id)
	if thread_id:
		base_query = base_query.where(EmailImportModel.thread_id == thread_id)
	if source:
		base_query = base_query.where(EmailImportModel.source == source)
	if search:
		search_filter = or_(
			EmailImportModel.subject.ilike(f"%{search}%"),
			EmailImportModel.from_address.ilike(f"%{search}%"),
			EmailImportModel.body_text.ilike(f"%{search}%"),
		)
		base_query = base_query.where(search_filter)

	# Count total
	count_stmt = select(func.count()).select_from(base_query.subquery())
	total = (await session.execute(count_stmt)).scalar() or 0

	# Fetch page
	stmt = base_query.options(
		selectinload(EmailImportModel.attachments)
	).order_by(
		EmailImportModel.sent_date.desc().nullslast()
	).offset((page - 1) * page_size).limit(page_size)

	result = await session.execute(stmt)
	imports = result.scalars().all()

	items = [
		EmailImportInfo(
			id=imp.id,
			message_id=imp.message_id,
			thread_id=imp.thread_id,
			document_id=imp.document_id,
			subject=imp.subject,
			from_address=imp.from_address,
			from_name=imp.from_name,
			to_addresses=imp.to_addresses or [],
			cc_addresses=imp.cc_addresses or [],
			sent_date=imp.sent_date,
			has_attachments=imp.has_attachments,
			attachment_count=imp.attachment_count,
			source=imp.source,
			import_status=imp.import_status,
			import_error=imp.import_error,
			folder_id=imp.folder_id,
			attachments=[
				EmailAttachmentInfo(
					id=att.id,
					filename=att.filename,
					content_type=att.content_type,
					size_bytes=att.size_bytes,
					content_id=att.content_id,
					is_inline=att.is_inline,
					document_id=att.document_id,
					import_status=att.import_status,
					import_error=att.import_error,
				) for att in imp.attachments
			],
			created_at=imp.created_at,
		) for imp in imports
	]

	return EmailImportListResponse(
		items=items,
		total=total,
		page=page,
		page_size=page_size,
	)


async def delete_email_import(
	session: AsyncSession,
	import_id: str,
	owner_id: str,
) -> bool:
	"""Delete email import."""
	stmt = select(EmailImportModel).where(
		and_(
			EmailImportModel.id == import_id,
			EmailImportModel.owner_id == owner_id,
		)
	)
	result = await session.execute(stmt)
	email_import = result.scalar_one_or_none()

	if not email_import:
		return False

	await session.delete(email_import)
	await session.commit()
	return True


# ----- Email Thread -----

async def get_or_create_thread(
	session: AsyncSession,
	thread_id: str,
	subject: str,
	owner_id: str,
	folder_id: str | None = None,
) -> EmailThreadModel:
	"""Get existing thread or create new one."""
	stmt = select(EmailThreadModel).where(
		EmailThreadModel.thread_id == thread_id
	)
	result = await session.execute(stmt)
	thread = result.scalar_one_or_none()

	if thread:
		return thread

	thread = EmailThreadModel(
		id=uuid7str(),
		thread_id=thread_id,
		subject=subject,
		message_count=0,
		owner_id=owner_id,
		folder_id=folder_id,
	)
	session.add(thread)
	return thread


async def get_email_thread(
	session: AsyncSession,
	thread_model_id: str,
	include_messages: bool = False,
) -> EmailThreadModel | None:
	"""Get email thread by model ID."""
	stmt = select(EmailThreadModel).where(
		EmailThreadModel.id == thread_model_id
	)
	if include_messages:
		stmt = stmt.options(selectinload(EmailThreadModel.imports))
	result = await session.execute(stmt)
	return result.scalar_one_or_none()


async def list_email_threads(
	session: AsyncSession,
	owner_id: str,
	page: int = 1,
	page_size: int = 50,
	folder_id: str | None = None,
	search: str | None = None,
) -> EmailThreadListResponse:
	"""List email threads with pagination."""
	base_query = select(EmailThreadModel).where(
		EmailThreadModel.owner_id == owner_id
	)

	if folder_id:
		base_query = base_query.where(EmailThreadModel.folder_id == folder_id)
	if search:
		base_query = base_query.where(EmailThreadModel.subject.ilike(f"%{search}%"))

	# Count
	count_stmt = select(func.count()).select_from(base_query.subquery())
	total = (await session.execute(count_stmt)).scalar() or 0

	# Fetch
	stmt = base_query.order_by(
		EmailThreadModel.last_message_date.desc().nullslast()
	).offset((page - 1) * page_size).limit(page_size)

	result = await session.execute(stmt)
	threads = result.scalars().all()

	items = [
		EmailThreadInfo(
			id=t.id,
			thread_id=t.thread_id,
			subject=t.subject,
			message_count=t.message_count,
			first_message_date=t.first_message_date,
			last_message_date=t.last_message_date,
			participants=t.participants or [],
			folder_id=t.folder_id,
		) for t in threads
	]

	return EmailThreadListResponse(
		items=items,
		total=total,
		page=page,
		page_size=page_size,
	)


# ----- Email Account -----

async def create_email_account(
	session: AsyncSession,
	data: EmailAccountCreate,
	owner_id: str,
) -> EmailAccountModel:
	"""Create email account for ingestion."""
	from papermerge.core.security import encrypt_secret

	account = EmailAccountModel(
		id=uuid7str(),
		name=data.name,
		account_type=data.account_type.value,
		email_address=data.email_address,
		imap_host=data.imap_host,
		imap_port=data.imap_port,
		imap_use_ssl=data.imap_use_ssl,
		imap_username=data.imap_username,
		imap_password_encrypted=encrypt_secret(data.imap_password) if data.imap_password else None,
		oauth_provider=data.oauth_provider,
		oauth_tenant_id=data.oauth_tenant_id,
		oauth_client_id=data.oauth_client_id,
		oauth_client_secret_encrypted=encrypt_secret(data.oauth_client_secret) if data.oauth_client_secret else None,
		sync_enabled=data.sync_enabled,
		sync_folders=data.sync_folders,
		sync_interval_minutes=data.sync_interval_minutes,
		target_folder_id=data.target_folder_id,
		auto_process=data.auto_process,
		import_attachments=data.import_attachments,
		attachment_filter=data.attachment_filter,
		owner_id=owner_id,
	)
	session.add(account)
	await session.commit()
	await session.refresh(account)
	return account


async def get_email_account(
	session: AsyncSession,
	account_id: str,
) -> EmailAccountModel | None:
	"""Get email account by ID."""
	stmt = select(EmailAccountModel).where(
		EmailAccountModel.id == account_id
	)
	result = await session.execute(stmt)
	return result.scalar_one_or_none()


async def update_email_account(
	session: AsyncSession,
	account_id: str,
	data: EmailAccountUpdate,
	owner_id: str,
) -> EmailAccountModel | None:
	"""Update email account."""
	from papermerge.core.security import encrypt_secret

	stmt = select(EmailAccountModel).where(
		and_(
			EmailAccountModel.id == account_id,
			EmailAccountModel.owner_id == owner_id,
		)
	)
	result = await session.execute(stmt)
	account = result.scalar_one_or_none()

	if not account:
		return None

	update_data = data.model_dump(exclude_unset=True)

	# Handle password encryption
	if "imap_password" in update_data:
		pwd = update_data.pop("imap_password")
		if pwd:
			account.imap_password_encrypted = encrypt_secret(pwd)

	for key, value in update_data.items():
		setattr(account, key, value)

	await session.commit()
	await session.refresh(account)
	return account


async def delete_email_account(
	session: AsyncSession,
	account_id: str,
	owner_id: str,
) -> bool:
	"""Delete email account."""
	stmt = select(EmailAccountModel).where(
		and_(
			EmailAccountModel.id == account_id,
			EmailAccountModel.owner_id == owner_id,
		)
	)
	result = await session.execute(stmt)
	account = result.scalar_one_or_none()

	if not account:
		return False

	await session.delete(account)
	await session.commit()
	return True


async def list_email_accounts(
	session: AsyncSession,
	owner_id: str,
) -> EmailAccountListResponse:
	"""List email accounts for user."""
	stmt = select(EmailAccountModel).where(
		EmailAccountModel.owner_id == owner_id
	).order_by(EmailAccountModel.name)

	result = await session.execute(stmt)
	accounts = result.scalars().all()

	items = [
		EmailAccountInfo(
			id=a.id,
			name=a.name,
			account_type=a.account_type,
			email_address=a.email_address,
			sync_enabled=a.sync_enabled,
			sync_folders=a.sync_folders or [],
			last_sync_at=a.last_sync_at,
			sync_interval_minutes=a.sync_interval_minutes,
			target_folder_id=a.target_folder_id,
			auto_process=a.auto_process,
			import_attachments=a.import_attachments,
			is_active=a.is_active,
			connection_status=a.connection_status,
			connection_error=a.connection_error,
			created_at=a.created_at,
		) for a in accounts
	]

	return EmailAccountListResponse(
		items=items,
		total=len(items),
	)


# ----- Email Rules -----

async def create_email_rule(
	session: AsyncSession,
	data: EmailRuleCreate,
	owner_id: str,
) -> EmailRuleModel:
	"""Create email processing rule."""
	rule = EmailRuleModel(
		id=uuid7str(),
		name=data.name,
		description=data.description,
		account_id=data.account_id,
		is_active=data.is_active,
		priority=data.priority,
		conditions=[c.model_dump() for c in data.conditions],
		actions=[a.model_dump() for a in data.actions],
		owner_id=owner_id,
	)
	session.add(rule)
	await session.commit()
	await session.refresh(rule)
	return rule


async def get_email_rule(
	session: AsyncSession,
	rule_id: str,
) -> EmailRuleModel | None:
	"""Get email rule by ID."""
	stmt = select(EmailRuleModel).where(
		EmailRuleModel.id == rule_id
	)
	result = await session.execute(stmt)
	return result.scalar_one_or_none()


async def update_email_rule(
	session: AsyncSession,
	rule_id: str,
	data: EmailRuleUpdate,
	owner_id: str,
) -> EmailRuleModel | None:
	"""Update email rule."""
	stmt = select(EmailRuleModel).where(
		and_(
			EmailRuleModel.id == rule_id,
			EmailRuleModel.owner_id == owner_id,
		)
	)
	result = await session.execute(stmt)
	rule = result.scalar_one_or_none()

	if not rule:
		return None

	update_data = data.model_dump(exclude_unset=True)

	if "conditions" in update_data:
		update_data["conditions"] = [c.model_dump() if hasattr(c, "model_dump") else c for c in update_data["conditions"]]
	if "actions" in update_data:
		update_data["actions"] = [a.model_dump() if hasattr(a, "model_dump") else a for a in update_data["actions"]]

	for key, value in update_data.items():
		setattr(rule, key, value)

	await session.commit()
	await session.refresh(rule)
	return rule


async def delete_email_rule(
	session: AsyncSession,
	rule_id: str,
	owner_id: str,
) -> bool:
	"""Delete email rule."""
	stmt = select(EmailRuleModel).where(
		and_(
			EmailRuleModel.id == rule_id,
			EmailRuleModel.owner_id == owner_id,
		)
	)
	result = await session.execute(stmt)
	rule = result.scalar_one_or_none()

	if not rule:
		return False

	await session.delete(rule)
	await session.commit()
	return True


async def list_email_rules(
	session: AsyncSession,
	owner_id: str,
	account_id: str | None = None,
) -> EmailRuleListResponse:
	"""List email rules for user."""
	stmt = select(EmailRuleModel).where(
		EmailRuleModel.owner_id == owner_id
	)

	if account_id:
		stmt = stmt.where(
			or_(
				EmailRuleModel.account_id == account_id,
				EmailRuleModel.account_id.is_(None),
			)
		)

	stmt = stmt.order_by(EmailRuleModel.priority, EmailRuleModel.name)

	result = await session.execute(stmt)
	rules = result.scalars().all()

	from .views import RuleCondition, RuleAction

	items = [
		EmailRuleInfo(
			id=r.id,
			name=r.name,
			description=r.description,
			account_id=r.account_id,
			is_active=r.is_active,
			priority=r.priority,
			conditions=[RuleCondition(**c) for c in (r.conditions or [])],
			actions=[RuleAction(**a) for a in (r.actions or [])],
			created_at=r.created_at,
		) for r in rules
	]

	return EmailRuleListResponse(
		items=items,
		total=len(items),
	)


async def evaluate_rules(
	session: AsyncSession,
	email: ParsedEmail,
	owner_id: str,
	account_id: str | None = None,
) -> list[dict]:
	"""
	Evaluate email against rules and return matching actions.

	Returns list of actions from matching rules.
	"""
	rules_response = await list_email_rules(session, owner_id, account_id)
	matching_actions = []

	for rule in rules_response.items:
		if not rule.is_active:
			continue

		if _matches_conditions(email, rule.conditions):
			for action in rule.actions:
				matching_actions.append({
					"rule_id": rule.id,
					"rule_name": rule.name,
					**action.model_dump(),
				})

	return matching_actions


def _matches_conditions(email: ParsedEmail, conditions: list) -> bool:
	"""Check if email matches all conditions."""
	import re

	for cond in conditions:
		field = cond.field
		operator = cond.operator
		value = cond.value

		# Get field value from email
		if field == "from":
			field_value = email.from_address
		elif field == "to":
			field_value = ", ".join(email.to_addresses)
		elif field == "cc":
			field_value = ", ".join(email.cc_addresses)
		elif field == "subject":
			field_value = email.subject or ""
		elif field == "body":
			field_value = email.body_text or ""
		elif field == "attachment_name":
			field_value = ", ".join(a.filename for a in email.attachments)
		elif field == "attachment_type":
			field_value = ", ".join(a.content_type for a in email.attachments)
		else:
			continue

		# Evaluate condition
		match = False
		if operator == "equals":
			match = field_value.lower() == (value or "").lower()
		elif operator == "contains":
			match = (value or "").lower() in field_value.lower()
		elif operator == "starts_with":
			match = field_value.lower().startswith((value or "").lower())
		elif operator == "ends_with":
			match = field_value.lower().endswith((value or "").lower())
		elif operator == "matches":
			try:
				match = bool(re.search(value or "", field_value, re.IGNORECASE))
			except re.error:
				match = False
		elif operator == "exists":
			match = bool(field_value)

		if not match:
			return False

	return True
