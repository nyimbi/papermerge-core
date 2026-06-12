from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TenantSettings(BaseModel):
	model_config = ConfigDict(extra="forbid")

	id: str = ""
	name: str = ""
	domain: str = ""
	logo_url: str | None = None
	primary_color: str | None = None
	timezone: str = "UTC"
	default_language: str = "en"
	date_format: str = "YYYY-MM-DD"
	number_format: str = "eu_dot"
	created_at: str = ""
	updated_at: str = ""


class TenantSettingsUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid")

	name: str | None = None
	domain: str | None = None
	logo_url: str | None = None
	primary_color: str | None = None
	timezone: str | None = None
	default_language: str | None = None
	date_format: str | None = None
	number_format: str | None = None


class StorageSettings(BaseModel):
	model_config = ConfigDict(extra="forbid")

	provider: str = "local"
	bucket_name: str | None = None
	region: str | None = None
	total_storage_bytes: int = 0
	used_storage_bytes: int = 0
	max_file_size_mb: int = 100
	allowed_file_types: list[str] = Field(default_factory=lambda: ["pdf", "doc", "docx", "jpg", "png", "tiff"])
	auto_archive_days: int | None = None
	archive_tier: str = "hot"
	versioning_enabled: bool = True
	max_versions: int = 10


class StorageSettingsUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid")

	provider: str | None = None
	bucket_name: str | None = None
	region: str | None = None
	max_file_size_mb: int | None = None
	allowed_file_types: list[str] | None = None
	auto_archive_days: int | None = None
	archive_tier: str | None = None
	versioning_enabled: bool | None = None
	max_versions: int | None = None


class OCRSettings(BaseModel):
	model_config = ConfigDict(extra="forbid")

	default_engine: str = "tesseract"
	default_language: str = "eng"
	supported_languages: list[str] = Field(default_factory=lambda: ["eng", "deu", "fra", "spa"])
	auto_ocr_enabled: bool = True
	auto_classify_enabled: bool = False
	confidence_threshold: float = 0.8
	fallback_engine: str | None = None
	gpu_acceleration: bool = False


class OCRSettingsUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid")

	default_engine: str | None = None
	default_language: str | None = None
	supported_languages: list[str] | None = None
	auto_ocr_enabled: bool | None = None
	auto_classify_enabled: bool | None = None
	confidence_threshold: float | None = None
	fallback_engine: str | None = None
	gpu_acceleration: bool | None = None


class SearchSettings(BaseModel):
	model_config = ConfigDict(extra="forbid")

	backend: str = "postgres"
	semantic_search_enabled: bool = False
	embedding_model: str = "text-embedding-3-small"
	index_on_upload: bool = True
	fuzzy_matching: bool = True
	min_score_threshold: float = 0.0
	max_results: int = 50
	highlight_enabled: bool = True


class SearchSettingsUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid")

	backend: str | None = None
	semantic_search_enabled: bool | None = None
	embedding_model: str | None = None
	index_on_upload: bool | None = None
	fuzzy_matching: bool | None = None
	min_score_threshold: float | None = None
	max_results: int | None = None
	highlight_enabled: bool | None = None


class WorkflowSettings(BaseModel):
	model_config = ConfigDict(extra="forbid")

	auto_routing_enabled: bool = False
	approval_timeout_hours: int = 48
	escalation_enabled: bool = False
	max_parallel_tasks: int = 10
	retry_failed_tasks: bool = True
	max_retries: int = 3
	email_notifications: bool = True
	slack_notifications: bool = False
	webhook_notifications: bool = False


class WorkflowSettingsUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid")

	auto_routing_enabled: bool | None = None
	approval_timeout_hours: int | None = None
	escalation_enabled: bool | None = None
	max_parallel_tasks: int | None = None
	retry_failed_tasks: bool | None = None
	max_retries: int | None = None
	email_notifications: bool | None = None
	slack_notifications: bool | None = None
	webhook_notifications: bool | None = None


class EmailSettings(BaseModel):
	"""SMTP/IMAP settings — smtp_password never returned in responses."""
	model_config = ConfigDict(extra="forbid")

	smtp_host: str | None = None
	smtp_port: int = 587
	smtp_username: str | None = None
	smtp_use_tls: bool = True
	from_address: str = "noreply@example.com"
	from_name: str = "dArchiva"
	reply_to: str | None = None
	email_templates_enabled: bool = True
	imap_enabled: bool = False
	imap_host: str | None = None
	imap_port: int = 993
	auto_import_enabled: bool = False
	import_folder: str = "INBOX"


class EmailSettingsUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid")

	smtp_host: str | None = None
	smtp_port: int | None = None
	smtp_username: str | None = None
	smtp_password: str | None = None  # accepted on write, never echoed back
	smtp_use_tls: bool | None = None
	from_address: str | None = None
	from_name: str | None = None
	reply_to: str | None = None
	email_templates_enabled: bool | None = None
	imap_enabled: bool | None = None
	imap_host: str | None = None
	imap_port: int | None = None
	auto_import_enabled: bool | None = None
	import_folder: str | None = None


class EmailTestResult(BaseModel):
	model_config = ConfigDict(extra="forbid")

	success: bool
	error: str | None = None


class SecuritySettings(BaseModel):
	model_config = ConfigDict(extra="forbid")

	mfa_required: bool = False
	mfa_methods: list[str] = Field(default_factory=lambda: ["totp"])
	passkeys_enabled: bool = False
	session_timeout_minutes: int = 480
	password_min_length: int = 12
	password_require_special: bool = True
	password_require_numbers: bool = True
	password_require_uppercase: bool = True
	password_expiry_days: int | None = None
	max_login_attempts: int = 5
	lockout_duration_minutes: int = 30
	ip_whitelist: list[str] = Field(default_factory=list)
	audit_log_retention_days: int = 365
	sensitive_data_masking: bool = False


class SecuritySettingsUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid")

	mfa_required: bool | None = None
	mfa_methods: list[str] | None = None
	passkeys_enabled: bool | None = None
	session_timeout_minutes: int | None = None
	password_min_length: int | None = None
	password_require_special: bool | None = None
	password_require_numbers: bool | None = None
	password_require_uppercase: bool | None = None
	password_expiry_days: int | None = None
	max_login_attempts: int | None = None
	lockout_duration_minutes: int | None = None
	ip_whitelist: list[str] | None = None
	audit_log_retention_days: int | None = None
	sensitive_data_masking: bool | None = None


class OAuthProvider(BaseModel):
	model_config = ConfigDict(extra="forbid")

	id: str
	name: str
	enabled: bool = False
	client_id: str | None = None
	scopes: list[str] = Field(default_factory=list)


class WebhookConfig(BaseModel):
	model_config = ConfigDict(extra="forbid")

	id: str
	name: str
	url: str
	events: list[str] = Field(default_factory=list)
	active: bool = True
	secret: str | None = None
	created_at: str


class WebhookConfigCreate(BaseModel):
	model_config = ConfigDict(extra="forbid")

	name: str
	url: str
	events: list[str] = Field(default_factory=list)
	active: bool = True
	secret: str | None = None


class WebhookConfigUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid")

	name: str | None = None
	url: str | None = None
	events: list[str] | None = None
	active: bool | None = None
	secret: str | None = None


class IntegrationSettings(BaseModel):
	model_config = ConfigDict(extra="forbid")

	oauth_providers: list[OAuthProvider] = Field(default_factory=list)
	webhooks: list[WebhookConfig] = Field(default_factory=list)
	api_rate_limit: int = 1000
	api_key_enabled: bool = True


class OAuthProviderUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid")

	enabled: bool | None = None
	client_id: str | None = None
	client_secret: str | None = None  # accepted on write, never echoed
	scopes: list[str] | None = None


class NotificationPreferences(BaseModel):
	model_config = ConfigDict(extra="forbid")

	email_enabled: bool = True
	digest_frequency: str = "daily"  # never | daily | weekly
	inapp_enabled: bool = True
	desktop_enabled: bool = False
	sound_enabled: bool = True
	dnd_enabled: bool = False
	dnd_start: str = "22:00"
	dnd_end: str = "08:00"
	# Event-specific toggles
	notify_on_upload: bool = True
	notify_on_ocr_complete: bool = True
	notify_on_share: bool = True
	notify_on_approval: bool = True
	notify_on_comment: bool = True
	notify_on_system_alerts: bool = True


class NotificationPreferencesUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid")

	email_enabled: bool | None = None
	digest_frequency: str | None = None
	inapp_enabled: bool | None = None
	desktop_enabled: bool | None = None
	sound_enabled: bool | None = None
	dnd_enabled: bool | None = None
	dnd_start: str | None = None
	dnd_end: str | None = None
	notify_on_upload: bool | None = None
	notify_on_ocr_complete: bool | None = None
	notify_on_share: bool | None = None
	notify_on_approval: bool | None = None
	notify_on_comment: bool | None = None
	notify_on_system_alerts: bool | None = None
