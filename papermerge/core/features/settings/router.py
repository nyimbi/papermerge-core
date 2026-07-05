from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import RootModel
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import scopes
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.settings.db import api as settings_api
from papermerge.core.features.settings.db.orm import (
	SystemSettings,
	WebhookConfig as WebhookORM,
)
from papermerge.core.features.settings.schema import (
	EmailSettings,
	EmailSettingsUpdate,
	EmailTestResult,
	IntegrationSettings,
	NotificationPreferences,
	NotificationPreferencesUpdate,
	OCRSettings,
	OCRSettingsUpdate,
	OAuthProvider,
	OAuthProviderUpdate,
	SearchSettings,
	SearchSettingsUpdate,
	SecuritySettings,
	SecuritySettingsUpdate,
	StorageSettings,
	StorageSettingsUpdate,
	TenantSettings,
	TenantSettingsUpdate,
	WebhookConfig,
	WebhookConfigCreate,
	WebhookConfigUpdate,
	WorkflowSettings,
	WorkflowSettingsUpdate,
)

router = APIRouter(
	prefix="/settings",
	tags=["settings"],
)


class SettingsMap(RootModel[dict[str, Any]]):
	"""Root settings map keyed by setting category."""


class SettingsPatch(RootModel[dict[str, dict[str, Any]]]):
	"""Patch payload keyed by setting category."""

# ---------------------------------------------------------------------------
# Defaults — returned when no DB row exists yet
# ---------------------------------------------------------------------------

_DEFAULTS: dict[str, Any] = {
	"tenant": TenantSettings().model_dump(),
	"storage": StorageSettings().model_dump(),
	"ocr": OCRSettings().model_dump(),
	"search": SearchSettings().model_dump(),
	"workflow": WorkflowSettings().model_dump(),
	"email": EmailSettings().model_dump(),
	"security": SecuritySettings().model_dump(),
	"integrations": {
		"oauth_providers": [
			{"id": "google", "name": "Google", "enabled": False, "client_id": None, "scopes": ["openid", "email", "profile"]},
			{"id": "microsoft", "name": "Microsoft", "enabled": False, "client_id": None, "scopes": ["openid", "email", "profile"]},
			{"id": "github", "name": "GitHub", "enabled": False, "client_id": None, "scopes": ["user:email"]},
		],
		"webhooks": [],
		"api_rate_limit": 1000,
		"api_key_enabled": True,
	},
}


def _merge(defaults: dict[str, Any], stored: dict[str, Any]) -> dict[str, Any]:
	return {**defaults, **stored}


def _orm_webhook_to_schema(hook: WebhookORM) -> WebhookConfig:
	return WebhookConfig(
		id=hook.id,
		name=hook.name,
		url=hook.url,
		events=hook.events or [],
		active=hook.active,
		secret=hook.secret,
		created_at=hook.created_at.isoformat(),
	)


async def _get_all_settings(db: AsyncSession) -> dict[str, Any]:
	try:
		result = await db.execute(select(SystemSettings))
	except SQLAlchemyError:
		return {}
	return {row.id: row.settings or {} for row in result.scalars().all()}


@router.get("", response_model=SettingsMap)
async def get_settings(
	_user: require_scopes(scopes.NODE_VIEW),
	db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
	"""Return all persisted settings keyed by category."""
	return await _get_all_settings(db)


@router.patch("", response_model=SettingsMap)
async def patch_settings(
	body: SettingsPatch,
	user: require_scopes(scopes.NODE_VIEW),
	db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
	"""Patch settings categories and return the updated settings map."""
	try:
		for key, value in body.root.items():
			await settings_api.upsert_settings(db, key, value, str(user.id))
	except SQLAlchemyError:
		await db.rollback()
		return {}
	return await _get_all_settings(db)


# ---------------------------------------------------------------------------
# Tenant settings
# ---------------------------------------------------------------------------

@router.get("/tenant", response_model=TenantSettings)
async def get_tenant_settings(
	_user: require_scopes(scopes.NODE_VIEW),
	db: AsyncSession = Depends(get_db),
) -> TenantSettings:
	stored = await settings_api.get_settings(db, "tenant")
	return TenantSettings(**_merge(_DEFAULTS["tenant"], stored))


@router.patch("/tenant", response_model=TenantSettings)
async def patch_tenant_settings(
	body: TenantSettingsUpdate,
	user: require_scopes(scopes.NODE_CREATE),
	db: AsyncSession = Depends(get_db),
) -> TenantSettings:
	data = body.model_dump(exclude_none=True)
	stored = await settings_api.upsert_settings(db, "tenant", data, str(user.id))
	return TenantSettings(**_merge(_DEFAULTS["tenant"], stored))


# ---------------------------------------------------------------------------
# Storage settings
# ---------------------------------------------------------------------------

@router.get("/storage", response_model=StorageSettings)
async def get_storage_settings(
	_user: require_scopes(scopes.NODE_VIEW),
	db: AsyncSession = Depends(get_db),
) -> StorageSettings:
	stored = await settings_api.get_settings(db, "storage")
	return StorageSettings(**_merge(_DEFAULTS["storage"], stored))


@router.patch("/storage", response_model=StorageSettings)
async def patch_storage_settings(
	body: StorageSettingsUpdate,
	user: require_scopes(scopes.NODE_CREATE),
	db: AsyncSession = Depends(get_db),
) -> StorageSettings:
	data = body.model_dump(exclude_none=True)
	stored = await settings_api.upsert_settings(db, "storage", data, str(user.id))
	return StorageSettings(**_merge(_DEFAULTS["storage"], stored))


# ---------------------------------------------------------------------------
# OCR settings
# ---------------------------------------------------------------------------

@router.get("/ocr", response_model=OCRSettings)
async def get_ocr_settings(
	_user: require_scopes(scopes.NODE_VIEW),
	db: AsyncSession = Depends(get_db),
) -> OCRSettings:
	stored = await settings_api.get_settings(db, "ocr")
	return OCRSettings(**_merge(_DEFAULTS["ocr"], stored))


@router.patch("/ocr", response_model=OCRSettings)
async def patch_ocr_settings(
	body: OCRSettingsUpdate,
	user: require_scopes(scopes.NODE_CREATE),
	db: AsyncSession = Depends(get_db),
) -> OCRSettings:
	data = body.model_dump(exclude_none=True)
	stored = await settings_api.upsert_settings(db, "ocr", data, str(user.id))
	return OCRSettings(**_merge(_DEFAULTS["ocr"], stored))


# ---------------------------------------------------------------------------
# Search settings
# ---------------------------------------------------------------------------

@router.get("/search", response_model=SearchSettings)
async def get_search_settings(
	_user: require_scopes(scopes.NODE_VIEW),
	db: AsyncSession = Depends(get_db),
) -> SearchSettings:
	stored = await settings_api.get_settings(db, "search")
	return SearchSettings(**_merge(_DEFAULTS["search"], stored))


@router.patch("/search", response_model=SearchSettings)
async def patch_search_settings(
	body: SearchSettingsUpdate,
	user: require_scopes(scopes.NODE_CREATE),
	db: AsyncSession = Depends(get_db),
) -> SearchSettings:
	data = body.model_dump(exclude_none=True)
	stored = await settings_api.upsert_settings(db, "search", data, str(user.id))
	return SearchSettings(**_merge(_DEFAULTS["search"], stored))


# ---------------------------------------------------------------------------
# Workflow settings
# ---------------------------------------------------------------------------

@router.get("/workflow", response_model=WorkflowSettings)
async def get_workflow_settings(
	_user: require_scopes(scopes.NODE_VIEW),
	db: AsyncSession = Depends(get_db),
) -> WorkflowSettings:
	stored = await settings_api.get_settings(db, "workflow")
	return WorkflowSettings(**_merge(_DEFAULTS["workflow"], stored))


@router.patch("/workflow", response_model=WorkflowSettings)
async def patch_workflow_settings(
	body: WorkflowSettingsUpdate,
	user: require_scopes(scopes.NODE_CREATE),
	db: AsyncSession = Depends(get_db),
) -> WorkflowSettings:
	data = body.model_dump(exclude_none=True)
	stored = await settings_api.upsert_settings(db, "workflow", data, str(user.id))
	return WorkflowSettings(**_merge(_DEFAULTS["workflow"], stored))


# ---------------------------------------------------------------------------
# Email settings  (smtp_password stripped from GET responses)
# ---------------------------------------------------------------------------

def _strip_password(d: dict[str, Any]) -> dict[str, Any]:
	return {k: v for k, v in d.items() if k != "smtp_password"}


@router.get("/email", response_model=EmailSettings)
async def get_email_settings(
	_user: require_scopes(scopes.NODE_VIEW),
	db: AsyncSession = Depends(get_db),
) -> EmailSettings:
	stored = await settings_api.get_settings(db, "email")
	merged = _merge(_DEFAULTS["email"], _strip_password(stored))
	return EmailSettings(**merged)


@router.patch("/email", response_model=EmailSettings)
async def patch_email_settings(
	body: EmailSettingsUpdate,
	user: require_scopes(scopes.NODE_CREATE),
	db: AsyncSession = Depends(get_db),
) -> EmailSettings:
	data = body.model_dump(exclude_none=True)
	stored = await settings_api.upsert_settings(db, "email", data, str(user.id))
	return EmailSettings(**_merge(_DEFAULTS["email"], _strip_password(stored)))


@router.post("/email/test", response_model=EmailTestResult)
async def test_email_settings(
	user: require_scopes(scopes.NODE_CREATE),
	db: AsyncSession = Depends(get_db),
) -> EmailTestResult:
	import asyncio
	import smtplib
	import ssl

	stored = await settings_api.get_settings(db, "email")
	smtp_host = stored.get("smtp_host", "")
	if not smtp_host:
		return EmailTestResult(success=False, error="SMTP not configured")

	smtp_port = int(stored.get("smtp_port", 587))
	smtp_user = stored.get("smtp_user") or stored.get("smtp_username", "")
	smtp_password = stored.get("smtp_password", "")
	use_tls = stored.get("smtp_tls", False)
	use_ssl = stored.get("smtp_ssl", False) or smtp_port == 465

	def _connect() -> tuple[bool, str | None]:
		try:
			if use_ssl:
				ctx = ssl.create_default_context()
				server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10, context=ctx)
			else:
				server = smtplib.SMTP(smtp_host, smtp_port, timeout=10)
				if use_tls:
					server.starttls(context=ssl.create_default_context())
			if smtp_user and smtp_password:
				server.login(smtp_user, smtp_password)
			server.quit()
			return True, None
		except smtplib.SMTPAuthenticationError as e:
			return False, f"Authentication failed: {e.smtp_error.decode(errors='replace')}"
		except smtplib.SMTPConnectError as e:
			return False, f"Connection refused: {e}"
		except TimeoutError:
			return False, f"Connection timed out connecting to {smtp_host}:{smtp_port}"
		except Exception as e:
			return False, str(e)

	loop = asyncio.get_event_loop()
	ok, error = await loop.run_in_executor(None, _connect)
	return EmailTestResult(success=ok, error=error)


# ---------------------------------------------------------------------------
# Security settings
# ---------------------------------------------------------------------------

@router.get("/security", response_model=SecuritySettings)
async def get_security_settings(
	_user: require_scopes(scopes.NODE_VIEW),
	db: AsyncSession = Depends(get_db),
) -> SecuritySettings:
	stored = await settings_api.get_settings(db, "security")
	return SecuritySettings(**_merge(_DEFAULTS["security"], stored))


@router.patch("/security", response_model=SecuritySettings)
async def patch_security_settings(
	body: SecuritySettingsUpdate,
	user: require_scopes(scopes.NODE_CREATE),
	db: AsyncSession = Depends(get_db),
) -> SecuritySettings:
	data = body.model_dump(exclude_none=True)
	stored = await settings_api.upsert_settings(db, "security", data, str(user.id))
	return SecuritySettings(**_merge(_DEFAULTS["security"], stored))


# ---------------------------------------------------------------------------
# Integrations (OAuth + webhooks)
# ---------------------------------------------------------------------------

@router.get("/integrations", response_model=IntegrationSettings)
async def get_integrations(
	_user: require_scopes(scopes.NODE_VIEW),
	db: AsyncSession = Depends(get_db),
) -> IntegrationSettings:
	stored_int = await settings_api.get_settings(db, "integrations")
	merged = _merge(_DEFAULTS["integrations"], stored_int)

	# Hydrate live webhooks from dedicated table
	hooks_orm = await settings_api.get_webhooks(db)
	merged["webhooks"] = [_orm_webhook_to_schema(h).model_dump() for h in hooks_orm]

	return IntegrationSettings(**merged)


@router.patch("/integrations/oauth/{provider_id}", response_model=OAuthProvider)
async def patch_oauth_provider(
	provider_id: str,
	body: OAuthProviderUpdate,
	user: require_scopes(scopes.NODE_CREATE),
	db: AsyncSession = Depends(get_db),
) -> OAuthProvider:
	stored = await settings_api.get_settings(db, "integrations")
	merged = _merge(_DEFAULTS["integrations"], stored)
	providers: list[dict] = merged.get("oauth_providers", [])

	idx = next((i for i, p in enumerate(providers) if p["id"] == provider_id), None)
	if idx is None:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"OAuth provider '{provider_id}' not found")

	update_data = body.model_dump(exclude_none=True)
	# client_secret is stored but never echoed; remove it from the provider dict key
	update_data.pop("client_secret", None)
	providers[idx] = {**providers[idx], **update_data}
	merged["oauth_providers"] = providers

	await settings_api.upsert_settings(db, "integrations", merged, str(user.id))
	return OAuthProvider(**providers[idx])


# ---------------------------------------------------------------------------
# Webhooks (dedicated table)
# ---------------------------------------------------------------------------

@router.get("/webhooks", response_model=list[WebhookConfig])
async def list_webhooks(
	_user: require_scopes(scopes.NODE_VIEW),
	db: AsyncSession = Depends(get_db),
) -> list[WebhookConfig]:
	hooks = await settings_api.get_webhooks(db)
	return [_orm_webhook_to_schema(h) for h in hooks]


@router.post("/webhooks", response_model=WebhookConfig, status_code=status.HTTP_201_CREATED)
async def create_webhook(
	body: WebhookConfigCreate,
	_user: require_scopes(scopes.NODE_CREATE),
	db: AsyncSession = Depends(get_db),
) -> WebhookConfig:
	hook = await settings_api.create_webhook(db, body.model_dump())
	return _orm_webhook_to_schema(hook)


@router.patch("/webhooks/{webhook_id}", response_model=WebhookConfig)
async def update_webhook(
	webhook_id: str,
	body: WebhookConfigUpdate,
	_user: require_scopes(scopes.NODE_CREATE),
	db: AsyncSession = Depends(get_db),
) -> WebhookConfig:
	hook = await settings_api.update_webhook(db, webhook_id, body.model_dump(exclude_none=True))
	if hook is None:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")
	return _orm_webhook_to_schema(hook)


@router.delete("/webhooks/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
	webhook_id: str,
	_user: require_scopes(scopes.NODE_CREATE),
	db: AsyncSession = Depends(get_db),
) -> None:
	deleted = await settings_api.delete_webhook(db, webhook_id)
	if not deleted:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")


# ---------------------------------------------------------------------------
# Notification preferences (per-user)
# ---------------------------------------------------------------------------

@router.get("/notifications", response_model=NotificationPreferences)
async def get_notifications(
	user: require_scopes(scopes.NODE_VIEW),
	db: AsyncSession = Depends(get_db),
) -> NotificationPreferences:
	stored = await settings_api.get_notification_prefs(db, str(user.id))
	defaults = NotificationPreferences().model_dump()
	return NotificationPreferences(**_merge(defaults, stored))


@router.patch("/notifications", response_model=NotificationPreferences)
async def patch_notifications(
	body: NotificationPreferencesUpdate,
	user: require_scopes(scopes.NODE_VIEW),
	db: AsyncSession = Depends(get_db),
) -> NotificationPreferences:
	data = body.model_dump(exclude_none=True)
	stored = await settings_api.upsert_notification_prefs(db, str(user.id), data)
	defaults = NotificationPreferences().model_dump()
	return NotificationPreferences(**_merge(defaults, stored))
