# (c) Copyright Datacraft, 2026
"""Email ingestion and management feature."""

from .models import (
	EmailImportModel,
	EmailAttachmentModel,
	EmailThreadModel,
	EmailAccountModel,
	EmailRuleModel,
)
from .views import (
	EmailImportInfo,
	EmailImportCreate,
	EmailAttachmentInfo,
	EmailThreadInfo,
	EmailAccountInfo,
	EmailAccountCreate,
	EmailRuleInfo,
	EmailRuleCreate,
	ParsedEmail,
)
from .parser import EmailParser, parse_email_file, parse_email_bytes
from .service import (
	import_email,
	get_email_import,
	list_email_imports,
	get_email_thread,
	list_email_threads,
	create_email_account,
	list_email_accounts,
	create_email_rule,
	list_email_rules,
)

__all__ = [
	# Models
	"EmailImportModel",
	"EmailAttachmentModel",
	"EmailThreadModel",
	"EmailAccountModel",
	"EmailRuleModel",
	# Views
	"EmailImportInfo",
	"EmailImportCreate",
	"EmailAttachmentInfo",
	"EmailThreadInfo",
	"EmailAccountInfo",
	"EmailAccountCreate",
	"EmailRuleInfo",
	"EmailRuleCreate",
	"ParsedEmail",
	# Parser
	"EmailParser",
	"parse_email_file",
	"parse_email_bytes",
	# Service
	"import_email",
	"get_email_import",
	"list_email_imports",
	"get_email_thread",
	"list_email_threads",
	"create_email_account",
	"list_email_accounts",
	"create_email_rule",
	"list_email_rules",
]
