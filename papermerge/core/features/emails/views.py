# (c) Copyright Datacraft, 2026
"""Email feature Pydantic schemas."""
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field, EmailStr


class EmailImportStatus(str, Enum):
	"""Email import status."""
	PENDING = "pending"
	PROCESSING = "processing"
	COMPLETED = "completed"
	FAILED = "failed"


class EmailSource(str, Enum):
	"""Email import source."""
	UPLOAD = "upload"
	IMAP = "imap"
	API = "api"
	OUTLOOK = "outlook"
	GMAIL = "gmail"


class EmailAccountType(str, Enum):
	"""Email account type."""
	IMAP = "imap"
	GRAPH_API = "graph_api"
	GMAIL_API = "gmail_api"


class ConnectionStatus(str, Enum):
	"""Account connection status."""
	UNKNOWN = "unknown"
	CONNECTED = "connected"
	ERROR = "error"


class AttachmentStatus(str, Enum):
	"""Attachment import status."""
	PENDING = "pending"
	IMPORTED = "imported"
	SKIPPED = "skipped"
	FAILED = "failed"


# ----- Parsed Email -----

class ParsedAttachment(BaseModel):
	"""Parsed email attachment."""
	filename: str
	content_type: str
	size_bytes: int
	content_id: str | None = None
	is_inline: bool = False
	content: bytes | None = None  # Excluded from serialization

	model_config = ConfigDict(extra="forbid")


class ParsedEmail(BaseModel):
	"""Parsed email from EML/MIME."""
	message_id: str
	subject: str | None = None
	from_address: str
	from_name: str | None = None
	to_addresses: list[str] = []
	cc_addresses: list[str] = []
	bcc_addresses: list[str] = []
	reply_to: str | None = None
	in_reply_to: str | None = None
	references: list[str] = []
	sent_date: datetime | None = None
	received_date: datetime | None = None
	body_text: str | None = None
	body_html: str | None = None
	headers: dict[str, str] = {}
	attachments: list[ParsedAttachment] = []

	model_config = ConfigDict(extra="forbid")


# ----- Email Import -----

class EmailAddressInfo(BaseModel):
	"""Email address with optional name."""
	address: str
	name: str | None = None


class EmailAttachmentInfo(BaseModel):
	"""Email attachment information."""
	id: str
	filename: str
	content_type: str
	size_bytes: int
	content_id: str | None = None
	is_inline: bool
	document_id: str | None = None
	import_status: AttachmentStatus
	import_error: str | None = None

	model_config = ConfigDict(from_attributes=True)


class EmailImportInfo(BaseModel):
	"""Email import information."""
	id: str
	message_id: str
	thread_id: str | None = None
	document_id: str | None = None
	subject: str | None = None
	from_address: str
	from_name: str | None = None
	to_addresses: list[str] = []
	cc_addresses: list[str] = []
	sent_date: datetime | None = None
	has_attachments: bool
	attachment_count: int
	source: EmailSource
	import_status: EmailImportStatus
	import_error: str | None = None
	folder_id: str | None = None
	attachments: list[EmailAttachmentInfo] = []
	created_at: datetime

	model_config = ConfigDict(from_attributes=True)


class EmailImportCreate(BaseModel):
	"""Create email import from parsed email."""
	source: EmailSource = EmailSource.UPLOAD
	source_account_id: str | None = None
	folder_id: str | None = None
	import_attachments: bool = True
	attachment_filter: list[str] | None = None  # MIME types to import

	model_config = ConfigDict(extra="forbid")


class EmailImportListResponse(BaseModel):
	"""Paginated email import list."""
	items: list[EmailImportInfo]
	total: int
	page: int
	page_size: int


# ----- Email Thread -----

class EmailThreadInfo(BaseModel):
	"""Email thread information."""
	id: str
	thread_id: str
	subject: str
	message_count: int
	first_message_date: datetime | None
	last_message_date: datetime | None
	participants: list[EmailAddressInfo] = []
	folder_id: str | None = None

	model_config = ConfigDict(from_attributes=True)


class EmailThreadDetail(EmailThreadInfo):
	"""Email thread with messages."""
	messages: list[EmailImportInfo] = []


class EmailThreadListResponse(BaseModel):
	"""Paginated thread list."""
	items: list[EmailThreadInfo]
	total: int
	page: int
	page_size: int


# ----- Email Account -----

class EmailAccountCreate(BaseModel):
	"""Create email account."""
	name: str
	account_type: EmailAccountType
	email_address: EmailStr

	# IMAP settings
	imap_host: str | None = None
	imap_port: int = 993
	imap_use_ssl: bool = True
	imap_username: str | None = None
	imap_password: str | None = None  # Will be encrypted

	# OAuth settings
	oauth_provider: str | None = None
	oauth_tenant_id: str | None = None
	oauth_client_id: str | None = None
	oauth_client_secret: str | None = None  # Will be encrypted

	# Sync settings
	sync_enabled: bool = False
	sync_folders: list[str] = ["INBOX"]
	sync_interval_minutes: int = 15

	# Target settings
	target_folder_id: str | None = None
	auto_process: bool = True
	import_attachments: bool = True
	attachment_filter: list[str] | None = None

	model_config = ConfigDict(extra="forbid")


class EmailAccountUpdate(BaseModel):
	"""Update email account."""
	name: str | None = None
	imap_host: str | None = None
	imap_port: int | None = None
	imap_use_ssl: bool | None = None
	imap_username: str | None = None
	imap_password: str | None = None

	sync_enabled: bool | None = None
	sync_folders: list[str] | None = None
	sync_interval_minutes: int | None = None

	target_folder_id: str | None = None
	auto_process: bool | None = None
	import_attachments: bool | None = None
	attachment_filter: list[str] | None = None

	is_active: bool | None = None

	model_config = ConfigDict(extra="forbid")


class EmailAccountInfo(BaseModel):
	"""Email account information."""
	id: str
	name: str
	account_type: EmailAccountType
	email_address: str
	sync_enabled: bool
	sync_folders: list[str] = []
	last_sync_at: datetime | None = None
	sync_interval_minutes: int
	target_folder_id: str | None = None
	auto_process: bool
	import_attachments: bool
	is_active: bool
	connection_status: ConnectionStatus
	connection_error: str | None = None
	created_at: datetime

	model_config = ConfigDict(from_attributes=True)


class EmailAccountListResponse(BaseModel):
	"""Paginated account list."""
	items: list[EmailAccountInfo]
	total: int


# ----- Email Rules -----

class RuleCondition(BaseModel):
	"""Email rule condition."""
	field: str  # from, to, cc, subject, body, attachment_name, attachment_type
	operator: str  # equals, contains, starts_with, ends_with, matches, exists
	value: str | None = None

	model_config = ConfigDict(extra="forbid")


class RuleAction(BaseModel):
	"""Email rule action."""
	action: str  # move_to_folder, add_tag, set_document_type, skip_import, etc.
	value: str | None = None  # Folder ID, tag name, document type ID, etc.
	params: dict | None = None

	model_config = ConfigDict(extra="forbid")


class EmailRuleCreate(BaseModel):
	"""Create email rule."""
	name: str
	description: str | None = None
	account_id: str | None = None
	is_active: bool = True
	priority: int = 100
	conditions: list[RuleCondition]
	actions: list[RuleAction]

	model_config = ConfigDict(extra="forbid")


class EmailRuleUpdate(BaseModel):
	"""Update email rule."""
	name: str | None = None
	description: str | None = None
	is_active: bool | None = None
	priority: int | None = None
	conditions: list[RuleCondition] | None = None
	actions: list[RuleAction] | None = None

	model_config = ConfigDict(extra="forbid")


class EmailRuleInfo(BaseModel):
	"""Email rule information."""
	id: str
	name: str
	description: str | None
	account_id: str | None
	is_active: bool
	priority: int
	conditions: list[RuleCondition]
	actions: list[RuleAction]
	created_at: datetime

	model_config = ConfigDict(from_attributes=True)


class EmailRuleListResponse(BaseModel):
	"""Paginated rule list."""
	items: list[EmailRuleInfo]
	total: int


# ----- Sync Status -----

class SyncStatus(BaseModel):
	"""Email account sync status."""
	account_id: str
	account_name: str
	is_syncing: bool
	last_sync_at: datetime | None
	next_sync_at: datetime | None
	messages_synced: int = 0
	messages_pending: int = 0
	error: str | None = None


class SyncResult(BaseModel):
	"""Email sync result."""
	account_id: str
	started_at: datetime
	completed_at: datetime
	messages_fetched: int
	messages_imported: int
	attachments_imported: int
	errors: list[str] = []
