# (c) Copyright Datacraft, 2026
"""Email API router."""
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.auth import get_current_user
from papermerge.core.db.models import User

from .parser import parse_email_bytes
from .service import (
	import_email,
	get_email_import,
	list_email_imports,
	delete_email_import,
	get_email_thread,
	list_email_threads,
	create_email_account,
	get_email_account,
	update_email_account,
	delete_email_account,
	list_email_accounts,
	create_email_rule,
	get_email_rule,
	update_email_rule,
	delete_email_rule,
	list_email_rules,
	evaluate_rules,
)
from .views import (
	ParsedEmail,
	EmailImportCreate,
	EmailImportInfo,
	EmailImportListResponse,
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
	EmailSource,
)

logger = logging.getLogger(__name__)

router = APIRouter(
	prefix="/emails",
	tags=["emails"],
)


# ----- Email Import -----

@router.post("/import", response_model=EmailImportInfo)
async def import_email_file(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	file: UploadFile = File(...),
	folder_id: str | None = Query(None),
	import_attachments: bool = Query(True),
):
	"""
	Import an email from uploaded .eml or .msg file.

	Parses the email, extracts metadata and attachments,
	and stores in the document management system.
	"""
	content = await file.read()

	# Parse email
	try:
		parsed = parse_email_bytes(content)
	except Exception as e:
		logger.error(f"Failed to parse email: {e}")
		raise HTTPException(status_code=400, detail=f"Failed to parse email: {str(e)}")

	# Import options
	options = EmailImportCreate(
		source=EmailSource.UPLOAD,
		folder_id=folder_id,
		import_attachments=import_attachments,
	)

	# Evaluate rules
	actions = await evaluate_rules(session, parsed, user.id)
	for action in actions:
		if action["action"] == "skip_import":
			raise HTTPException(status_code=400, detail="Email skipped by rule")
		if action["action"] == "move_to_folder" and action.get("value"):
			options.folder_id = action["value"]

	# Import
	email_import = await import_email(session, parsed, options, user.id)

	return EmailImportInfo(
		id=email_import.id,
		message_id=email_import.message_id,
		thread_id=email_import.thread_id,
		document_id=email_import.document_id,
		subject=email_import.subject,
		from_address=email_import.from_address,
		from_name=email_import.from_name,
		to_addresses=email_import.to_addresses or [],
		cc_addresses=email_import.cc_addresses or [],
		sent_date=email_import.sent_date,
		has_attachments=email_import.has_attachments,
		attachment_count=email_import.attachment_count,
		source=email_import.source,
		import_status=email_import.import_status,
		import_error=email_import.import_error,
		folder_id=email_import.folder_id,
		attachments=[],
		created_at=email_import.created_at,
	)


@router.post("/import/raw", response_model=EmailImportInfo)
async def import_email_raw(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	parsed: ParsedEmail,
	options: EmailImportCreate | None = None,
):
	"""
	Import a pre-parsed email.

	Useful for programmatic imports from external systems.
	"""
	options = options or EmailImportCreate()
	email_import = await import_email(session, parsed, options, user.id)

	return EmailImportInfo(
		id=email_import.id,
		message_id=email_import.message_id,
		thread_id=email_import.thread_id,
		document_id=email_import.document_id,
		subject=email_import.subject,
		from_address=email_import.from_address,
		from_name=email_import.from_name,
		to_addresses=email_import.to_addresses or [],
		cc_addresses=email_import.cc_addresses or [],
		sent_date=email_import.sent_date,
		has_attachments=email_import.has_attachments,
		attachment_count=email_import.attachment_count,
		source=email_import.source,
		import_status=email_import.import_status,
		import_error=email_import.import_error,
		folder_id=email_import.folder_id,
		attachments=[],
		created_at=email_import.created_at,
	)


@router.get("/imports", response_model=EmailImportListResponse)
async def list_imports(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	page: int = Query(1, ge=1),
	page_size: int = Query(50, ge=1, le=100),
	folder_id: str | None = None,
	thread_id: str | None = None,
	search: str | None = None,
	source: str | None = None,
):
	"""List imported emails with filters."""
	return await list_email_imports(
		session,
		owner_id=user.id,
		page=page,
		page_size=page_size,
		folder_id=folder_id,
		thread_id=thread_id,
		search=search,
		source=source,
	)


@router.get("/imports/{import_id}", response_model=EmailImportInfo)
async def get_import(
	import_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
):
	"""Get email import details."""
	email_import = await get_email_import(session, import_id)

	if not email_import:
		raise HTTPException(status_code=404, detail="Email import not found")

	if email_import.owner_id != user.id:
		raise HTTPException(status_code=403, detail="Access denied")

	from .views import EmailAttachmentInfo

	return EmailImportInfo(
		id=email_import.id,
		message_id=email_import.message_id,
		thread_id=email_import.thread_id,
		document_id=email_import.document_id,
		subject=email_import.subject,
		from_address=email_import.from_address,
		from_name=email_import.from_name,
		to_addresses=email_import.to_addresses or [],
		cc_addresses=email_import.cc_addresses or [],
		sent_date=email_import.sent_date,
		has_attachments=email_import.has_attachments,
		attachment_count=email_import.attachment_count,
		source=email_import.source,
		import_status=email_import.import_status,
		import_error=email_import.import_error,
		folder_id=email_import.folder_id,
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
			) for att in email_import.attachments
		],
		created_at=email_import.created_at,
	)


@router.delete("/imports/{import_id}")
async def delete_import(
	import_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
):
	"""Delete email import."""
	success = await delete_email_import(session, import_id, user.id)

	if not success:
		raise HTTPException(status_code=404, detail="Email import not found")

	return {"status": "deleted"}


# ----- Email Threads -----

@router.get("/threads", response_model=EmailThreadListResponse)
async def list_threads(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	page: int = Query(1, ge=1),
	page_size: int = Query(50, ge=1, le=100),
	folder_id: str | None = None,
	search: str | None = None,
):
	"""List email threads."""
	return await list_email_threads(
		session,
		owner_id=user.id,
		page=page,
		page_size=page_size,
		folder_id=folder_id,
		search=search,
	)


@router.get("/threads/{thread_id}", response_model=EmailThreadDetail)
async def get_thread(
	thread_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
):
	"""Get email thread with messages."""
	thread = await get_email_thread(session, thread_id, include_messages=True)

	if not thread:
		raise HTTPException(status_code=404, detail="Thread not found")

	if thread.owner_id != user.id:
		raise HTTPException(status_code=403, detail="Access denied")

	from .views import EmailAddressInfo

	messages = []
	for imp in thread.imports:
		messages.append(EmailImportInfo(
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
			attachments=[],
			created_at=imp.created_at,
		))

	return EmailThreadDetail(
		id=thread.id,
		thread_id=thread.thread_id,
		subject=thread.subject,
		message_count=thread.message_count,
		first_message_date=thread.first_message_date,
		last_message_date=thread.last_message_date,
		participants=[EmailAddressInfo(**p) for p in (thread.participants or [])],
		folder_id=thread.folder_id,
		messages=messages,
	)


# ----- Email Accounts -----

@router.post("/accounts", response_model=EmailAccountInfo)
async def create_account(
	data: EmailAccountCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
):
	"""Create email account for ingestion."""
	account = await create_email_account(session, data, user.id)

	return EmailAccountInfo(
		id=account.id,
		name=account.name,
		account_type=account.account_type,
		email_address=account.email_address,
		sync_enabled=account.sync_enabled,
		sync_folders=account.sync_folders or [],
		last_sync_at=account.last_sync_at,
		sync_interval_minutes=account.sync_interval_minutes,
		target_folder_id=account.target_folder_id,
		auto_process=account.auto_process,
		import_attachments=account.import_attachments,
		is_active=account.is_active,
		connection_status=account.connection_status,
		connection_error=account.connection_error,
		created_at=account.created_at,
	)


@router.get("/accounts", response_model=EmailAccountListResponse)
async def list_accounts(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
):
	"""List email accounts."""
	return await list_email_accounts(session, user.id)


@router.get("/accounts/{account_id}", response_model=EmailAccountInfo)
async def get_account(
	account_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
):
	"""Get email account details."""
	account = await get_email_account(session, account_id)

	if not account:
		raise HTTPException(status_code=404, detail="Account not found")

	if account.owner_id != user.id:
		raise HTTPException(status_code=403, detail="Access denied")

	return EmailAccountInfo(
		id=account.id,
		name=account.name,
		account_type=account.account_type,
		email_address=account.email_address,
		sync_enabled=account.sync_enabled,
		sync_folders=account.sync_folders or [],
		last_sync_at=account.last_sync_at,
		sync_interval_minutes=account.sync_interval_minutes,
		target_folder_id=account.target_folder_id,
		auto_process=account.auto_process,
		import_attachments=account.import_attachments,
		is_active=account.is_active,
		connection_status=account.connection_status,
		connection_error=account.connection_error,
		created_at=account.created_at,
	)


@router.patch("/accounts/{account_id}", response_model=EmailAccountInfo)
async def update_account(
	account_id: str,
	data: EmailAccountUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
):
	"""Update email account."""
	account = await update_email_account(session, account_id, data, user.id)

	if not account:
		raise HTTPException(status_code=404, detail="Account not found")

	return EmailAccountInfo(
		id=account.id,
		name=account.name,
		account_type=account.account_type,
		email_address=account.email_address,
		sync_enabled=account.sync_enabled,
		sync_folders=account.sync_folders or [],
		last_sync_at=account.last_sync_at,
		sync_interval_minutes=account.sync_interval_minutes,
		target_folder_id=account.target_folder_id,
		auto_process=account.auto_process,
		import_attachments=account.import_attachments,
		is_active=account.is_active,
		connection_status=account.connection_status,
		connection_error=account.connection_error,
		created_at=account.created_at,
	)


@router.delete("/accounts/{account_id}")
async def delete_account(
	account_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
):
	"""Delete email account."""
	success = await delete_email_account(session, account_id, user.id)

	if not success:
		raise HTTPException(status_code=404, detail="Account not found")

	return {"status": "deleted"}


@router.post("/accounts/{account_id}/test")
async def test_account_connection(
	account_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
):
	"""Test email account connection."""
	account = await get_email_account(session, account_id)

	if not account:
		raise HTTPException(status_code=404, detail="Account not found")

	if account.owner_id != user.id:
		raise HTTPException(status_code=403, detail="Access denied")

	# Test connection based on account type
	from .imap_client import (
		test_imap_connection,
		test_graph_api_connection,
		test_gmail_api_connection,
	)

	try:
		if account.account_type == "imap":
			success, message = await test_imap_connection(account)
		elif account.account_type == "graph_api":
			success, message = await test_graph_api_connection(account)
		elif account.account_type == "gmail_api":
			success, message = await test_gmail_api_connection(account)
		else:
			return {"success": False, "message": f"Unknown account type: {account.account_type}"}

		account.connection_status = "connected" if success else "error"
		account.connection_error = None if success else message
		await session.commit()
		return {"success": success, "message": message}

	except Exception as e:
		account.connection_status = "error"
		account.connection_error = str(e)
		await session.commit()
		return {"success": False, "message": str(e)}


@router.post("/accounts/{account_id}/sync")
async def trigger_sync(
	account_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
):
	"""Trigger manual sync for email account."""
	account = await get_email_account(session, account_id)

	if not account:
		raise HTTPException(status_code=404, detail="Account not found")

	if account.owner_id != user.id:
		raise HTTPException(status_code=403, detail="Access denied")

	# Queue sync task
	from papermerge.core.tasks import sync_email_account

	sync_email_account.delay(account_id, user.id)

	return {"status": "sync_queued", "account_id": account_id}


# ----- Email Rules -----

@router.post("/rules", response_model=EmailRuleInfo)
async def create_rule(
	data: EmailRuleCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
):
	"""Create email processing rule."""
	rule = await create_email_rule(session, data, user.id)

	from .views import RuleCondition, RuleAction

	return EmailRuleInfo(
		id=rule.id,
		name=rule.name,
		description=rule.description,
		account_id=rule.account_id,
		is_active=rule.is_active,
		priority=rule.priority,
		conditions=[RuleCondition(**c) for c in (rule.conditions or [])],
		actions=[RuleAction(**a) for a in (rule.actions or [])],
		created_at=rule.created_at,
	)


@router.get("/rules", response_model=EmailRuleListResponse)
async def list_rules(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	account_id: str | None = None,
):
	"""List email rules."""
	return await list_email_rules(session, user.id, account_id)


@router.get("/rules/{rule_id}", response_model=EmailRuleInfo)
async def get_rule(
	rule_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
):
	"""Get email rule details."""
	rule = await get_email_rule(session, rule_id)

	if not rule:
		raise HTTPException(status_code=404, detail="Rule not found")

	if rule.owner_id != user.id:
		raise HTTPException(status_code=403, detail="Access denied")

	from .views import RuleCondition, RuleAction

	return EmailRuleInfo(
		id=rule.id,
		name=rule.name,
		description=rule.description,
		account_id=rule.account_id,
		is_active=rule.is_active,
		priority=rule.priority,
		conditions=[RuleCondition(**c) for c in (rule.conditions or [])],
		actions=[RuleAction(**a) for a in (rule.actions or [])],
		created_at=rule.created_at,
	)


@router.patch("/rules/{rule_id}", response_model=EmailRuleInfo)
async def update_rule(
	rule_id: str,
	data: EmailRuleUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
):
	"""Update email rule."""
	rule = await update_email_rule(session, rule_id, data, user.id)

	if not rule:
		raise HTTPException(status_code=404, detail="Rule not found")

	from .views import RuleCondition, RuleAction

	return EmailRuleInfo(
		id=rule.id,
		name=rule.name,
		description=rule.description,
		account_id=rule.account_id,
		is_active=rule.is_active,
		priority=rule.priority,
		conditions=[RuleCondition(**c) for c in (rule.conditions or [])],
		actions=[RuleAction(**a) for a in (rule.actions or [])],
		created_at=rule.created_at,
	)


@router.delete("/rules/{rule_id}")
async def delete_rule(
	rule_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
):
	"""Delete email rule."""
	success = await delete_email_rule(session, rule_id, user.id)

	if not success:
		raise HTTPException(status_code=404, detail="Rule not found")

	return {"status": "deleted"}
