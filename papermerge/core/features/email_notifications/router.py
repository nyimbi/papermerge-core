# (c) Copyright Datacraft, 2026
"""REST endpoints for per-user dArchiva email notification preferences.

GET  /notifications/preferences  — retrieve current user's preferences
PUT  /notifications/preferences  — replace (full update) preferences
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import scopes
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.users.schema import User
from papermerge.core.features.email_notifications.preferences import (
	get_email_prefs,
	upsert_email_prefs,
)

router = APIRouter(
	prefix="/notifications",
	tags=["email-notifications"],
)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class EmailNotificationPreferences(BaseModel):
	model_config = ConfigDict(extra="forbid")

	batch_complete: bool = Field(True, description="Email when a batch reaches 'complete' status")
	sla_breach: bool = Field(True, description="Email on SLA warning or critical breach")
	exceptions: bool = Field(True, description="Email when a processing exception is raised")
	weekly_summary: bool = Field(False, description="Weekly KPI digest email")
	notification_email: str = Field("", description="Override email address (blank = use account email)")


class EmailNotificationPreferencesUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid")

	batch_complete: bool | None = None
	sla_breach: bool | None = None
	exceptions: bool | None = None
	weekly_summary: bool | None = None
	notification_email: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/preferences", response_model=EmailNotificationPreferences)
async def get_notification_preferences(
	user: Annotated[User, Depends(require_scopes(scopes.NODE_VIEW))],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> EmailNotificationPreferences:
	"""Return the current user's dArchiva email notification preferences."""
	prefs = await get_email_prefs(db, str(user.id))
	return EmailNotificationPreferences(**prefs)


@router.put("/preferences", response_model=EmailNotificationPreferences)
async def update_notification_preferences(
	body: EmailNotificationPreferencesUpdate,
	user: Annotated[User, Depends(require_scopes(scopes.NODE_VIEW))],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> EmailNotificationPreferences:
	"""Update the current user's dArchiva email notification preferences."""
	data = body.model_dump(exclude_none=True)
	prefs = await upsert_email_prefs(db, str(user.id), data)
	return EmailNotificationPreferences(**prefs)
