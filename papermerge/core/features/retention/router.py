# (c) Copyright Datacraft, 2026
"""FastAPI router for document retention policies."""
import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import get_current_user
from papermerge.core.features.users.schema import User
from papermerge.core.features.retention.db.orm import RetentionPolicy
from papermerge.core.utils.uuid_compat import uuid7str

logger = logging.getLogger(__name__)

router = APIRouter(
	prefix="/retention",
	tags=["retention"],
)

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class RetentionPolicyCreate(BaseModel):
	name: str
	description: str | None = None
	policy_type: str  # "archive" | "delete" | "move"
	after_days: int
	applies_to_project_id: str | None = None
	applies_to_document_type: str | None = None
	destination_folder_id: str | None = None
	is_active: bool = True


class RetentionPolicyUpdate(BaseModel):
	name: str | None = None
	description: str | None = None
	policy_type: str | None = None
	after_days: int | None = None
	applies_to_project_id: str | None = None
	applies_to_document_type: str | None = None
	destination_folder_id: str | None = None
	is_active: bool | None = None


class RetentionPolicyResponse(BaseModel):
	id: str
	name: str
	description: str | None
	policy_type: str
	after_days: int
	applies_to_project_id: str | None
	applies_to_document_type: str | None
	destination_folder_id: str | None
	is_active: bool
	tenant_id: str
	created_by_id: str | None
	created_at: datetime
	last_run_at: datetime | None
	docs_processed: int

	model_config = {"from_attributes": True}


class RunPolicyResponse(BaseModel):
	policy_id: str
	docs_processed: int
	dry_run: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _policy_or_404(policy: RetentionPolicy | None, policy_id: str) -> RetentionPolicy:
	if policy is None:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail=f"Retention policy {policy_id!r} not found",
		)
	return policy


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/policies", response_model=list[RetentionPolicyResponse])
async def list_policies(
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> list[RetentionPolicyResponse]:
	"""List all retention policies for the current tenant."""
	stmt = (
		select(RetentionPolicy)
		.where(RetentionPolicy.tenant_id == str(user.tenant_id))
		.order_by(RetentionPolicy.created_at.desc())
	)
	result = await db.execute(stmt)
	policies = result.scalars().all()
	return [RetentionPolicyResponse.model_validate(p) for p in policies]


@router.post(
	"/policies",
	response_model=RetentionPolicyResponse,
	status_code=status.HTTP_201_CREATED,
)
async def create_policy(
	body: RetentionPolicyCreate,
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> RetentionPolicyResponse:
	"""Create a new retention policy."""
	if body.policy_type not in ("archive", "delete", "move"):
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail="policy_type must be one of: archive, delete, move",
		)
	if body.policy_type == "move" and not body.destination_folder_id:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail="destination_folder_id is required for 'move' policy type",
		)
	policy = RetentionPolicy(
		id=uuid7str(),
		name=body.name,
		description=body.description,
		policy_type=body.policy_type,
		after_days=body.after_days,
		applies_to_project_id=body.applies_to_project_id,
		applies_to_document_type=body.applies_to_document_type,
		destination_folder_id=body.destination_folder_id,
		is_active=body.is_active,
		tenant_id=str(user.tenant_id),
		created_by_id=str(user.id),
		created_at=datetime.utcnow(),
		docs_processed=0,
	)
	db.add(policy)
	await db.commit()
	await db.refresh(policy)
	logger.info(f"Retention policy created: {policy.id} by user {user.id}")
	return RetentionPolicyResponse.model_validate(policy)


@router.patch("/policies/{policy_id}", response_model=RetentionPolicyResponse)
async def update_policy(
	policy_id: str,
	body: RetentionPolicyUpdate,
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> RetentionPolicyResponse:
	"""Update an existing retention policy."""
	policy = await db.get(RetentionPolicy, policy_id)
	_policy_or_404(policy, policy_id)
	assert policy is not None  # for type narrowing after 404 check

	if policy.tenant_id != str(user.tenant_id):
		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

	for field, value in body.model_dump(exclude_unset=True).items():
		setattr(policy, field, value)

	await db.commit()
	await db.refresh(policy)
	return RetentionPolicyResponse.model_validate(policy)


@router.delete("/policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy(
	policy_id: str,
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> None:
	"""Delete a retention policy."""
	policy = await db.get(RetentionPolicy, policy_id)
	_policy_or_404(policy, policy_id)
	assert policy is not None

	if policy.tenant_id != str(user.tenant_id):
		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

	await db.delete(policy)
	await db.commit()
	logger.info(f"Retention policy deleted: {policy_id} by user {user.id}")


@router.post("/policies/{policy_id}/run-now", response_model=RunPolicyResponse)
async def run_policy_now(
	policy_id: str,
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
	dry_run: bool = False,
) -> RunPolicyResponse:
	"""Manually trigger a sweep for a single retention policy."""
	from papermerge.core.tasks import run_retention_policy_task

	policy = await db.get(RetentionPolicy, policy_id)
	_policy_or_404(policy, policy_id)
	assert policy is not None

	if policy.tenant_id != str(user.tenant_id):
		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

	# Dispatch async celery task; for the HTTP response return a stub count.
	run_retention_policy_task.delay(policy_id=policy_id, dry_run=dry_run)
	logger.info(
		f"Manual retention sweep triggered: policy={policy_id} dry_run={dry_run} user={user.id}"
	)
	return RunPolicyResponse(policy_id=policy_id, docs_processed=0, dry_run=dry_run)
