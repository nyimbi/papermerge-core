# (c) Copyright Datacraft, 2026
"""Onboarding wizard router — tracks first-login setup steps per user."""

import logging
from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import String, DateTime, ForeignKey, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from papermerge.core.auth import get_current_user
from papermerge.core.db.base import Base
from papermerge.core.db.engine import get_db
from papermerge.core.features.users.schema import User

logger = logging.getLogger(__name__)

ALL_STEPS: list[str] = [
	"create_project",
	"configure_scanner",
	"set_quality_thresholds",
	"invite_operator",
]

router = APIRouter(
	prefix="/onboarding",
	tags=["onboarding"],
)


# ---------------------------------------------------------------------------
# ORM model (inline — feature is small enough not to warrant a models.py)
# ---------------------------------------------------------------------------

class UserOnboarding(Base):
	__tablename__ = "user_onboarding"

	id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
	user_id: Mapped[PG_UUID] = mapped_column(
		PG_UUID(as_uuid=True),
		ForeignKey("users.id", ondelete="CASCADE"),
		nullable=False,
		unique=True,
		index=True,
	)
	completed_steps: Mapped[str] = mapped_column(String(500), nullable=False, default="")
	created_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
	)
	updated_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
	)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class OnboardingStatus(BaseModel):
	completed_steps: list[str]
	all_steps: list[str]
	is_complete: bool


class CompleteStepRequest(BaseModel):
	step: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_steps(raw: str) -> list[str]:
	"""Deserialise comma-separated step string, dropping empties."""
	return [s for s in raw.split(",") if s]


def _serialize_steps(steps: list[str]) -> str:
	return ",".join(steps)


async def _get_or_create(db: AsyncSession, user_id) -> UserOnboarding:
	result = await db.execute(
		select(UserOnboarding).where(UserOnboarding.user_id == user_id)
	)
	row = result.scalar_one_or_none()
	if row is None:
		row = UserOnboarding(id=uuid4(), user_id=user_id, completed_steps="")
		db.add(row)
		await db.flush()
	return row


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/status", response_model=OnboardingStatus)
async def get_onboarding_status(
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> OnboardingStatus:
	"""Return completed steps and overall completion flag for the current user."""
	row = await _get_or_create(db, user.id)
	await db.commit()
	completed = _parse_steps(row.completed_steps)
	return OnboardingStatus(
		completed_steps=completed,
		all_steps=ALL_STEPS,
		is_complete=set(ALL_STEPS).issubset(set(completed)),
	)


@router.post("/complete-step", response_model=OnboardingStatus)
async def complete_step(
	body: CompleteStepRequest,
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> OnboardingStatus:
	"""Mark a single step as done for the current user."""
	if body.step not in ALL_STEPS:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail=f"Unknown step '{body.step}'. Valid steps: {ALL_STEPS}",
		)
	row = await _get_or_create(db, user.id)
	completed = _parse_steps(row.completed_steps)
	if body.step not in completed:
		completed.append(body.step)
		row.completed_steps = _serialize_steps(completed)
		row.updated_at = datetime.now(timezone.utc)
	await db.commit()
	return OnboardingStatus(
		completed_steps=completed,
		all_steps=ALL_STEPS,
		is_complete=set(ALL_STEPS).issubset(set(completed)),
	)


@router.post("/reset", response_model=OnboardingStatus)
async def reset_onboarding(
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> OnboardingStatus:
	"""Clear all completed steps for the current user (testing / debug only)."""
	row = await _get_or_create(db, user.id)
	row.completed_steps = ""
	row.updated_at = datetime.now(timezone.utc)
	await db.commit()
	return OnboardingStatus(
		completed_steps=[],
		all_steps=ALL_STEPS,
		is_complete=False,
	)
