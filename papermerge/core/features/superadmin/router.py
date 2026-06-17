# (c) Copyright Datacraft, 2026
"""Super-admin API router — platform-wide management.

All endpoints require the authenticated user to have is_superuser=True.
Auto-discovered by papermerge.core.router_loader.discover_routers().
"""
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import scopes
from papermerge.core.features.auth.dependencies import require_scopes

logger = logging.getLogger(__name__)

router = APIRouter(
	prefix="/superadmin",
	tags=["superadmin"],
)


# ── Dependency ────────────────────────────────────────────────────────────────

def _require_superuser(user=Depends(require_scopes(scopes.SYSTEM_ADMIN))):
	"""Dependency that verifies the user holds the SYSTEM_ADMIN scope.

	is_superuser users automatically receive all scopes (see auth/__init__.py),
	so this guards every endpoint against non-superuser callers.
	"""
	return user


# ── Response schemas ──────────────────────────────────────────────────────────

class TenantStats(BaseModel):
	"""Per-tenant summary for the admin table."""
	id: str
	name: str
	slug: str
	is_active: bool
	plan: str
	user_count: int
	document_count: int
	storage_mb: float
	created_at: datetime | None

	model_config = ConfigDict(from_attributes=True)


class TenantActivity(BaseModel):
	"""Recent activity entry for a single tenant."""
	timestamp: datetime
	description: str


class TenantDetail(BaseModel):
	"""Detailed view of a single tenant for the edit dialog."""
	id: str
	name: str
	slug: str
	is_active: bool
	plan: str
	contact_email: str | None
	max_users: int | None
	max_storage_gb: int | None
	features: dict | None
	user_count: int
	document_count: int
	storage_mb: float
	created_at: datetime | None
	recent_activity: list[TenantActivity]

	model_config = ConfigDict(from_attributes=True)


class TenantPatchRequest(BaseModel):
	"""Payload for patching a tenant via the super-admin panel."""
	is_active: bool | None = None
	storage_quota_gb: float | None = None
	feature_flags: dict | None = None


class SystemStats(BaseModel):
	"""Platform-wide aggregate statistics."""
	total_tenants: int
	total_users: int
	total_documents: int
	total_storage_gb: float
	documents_today: int
	new_users_today: int


class CreateTenantRequest(BaseModel):
	"""Minimal create-tenant request from the super-admin UI."""
	name: str
	slug: str
	plan: str = "free"
	contact_email: str | None = None
	max_users: int | None = None
	max_storage_gb: int | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _tenant_user_count(db: AsyncSession, tenant_id: UUID) -> int:
	from papermerge.core.features.users.db.orm import User
	stmt = select(func.count()).select_from(User).where(User.tenant_id == tenant_id)
	return await db.scalar(stmt) or 0


async def _tenant_doc_count(db: AsyncSession, tenant_id: UUID) -> int:
	from papermerge.core.features.document.db.orm import Document
	from papermerge.core.features.ownership.db.orm import Ownership
	from papermerge.core.features.users.db.orm import User
	stmt = (
		select(func.count())
		.select_from(Document)
		.join(
			Ownership,
			(Ownership.resource_id == Document.id)
			& (Ownership.owner_type == "user")
			& (Ownership.resource_type == "node"),
		)
		.join(User, User.id == Ownership.owner_id)
		.where(User.tenant_id == tenant_id)
	)
	return await db.scalar(stmt) or 0


async def _tenant_storage_mb(db: AsyncSession, tenant_id: UUID) -> float:
	"""Approximate storage via sum of DocumentVersion.size (bytes)."""
	try:
		from papermerge.core.features.document.db.orm import Document, DocumentVersion
		from papermerge.core.features.ownership.db.orm import Ownership
		from papermerge.core.features.users.db.orm import User
		stmt = (
			select(func.coalesce(func.sum(DocumentVersion.size), 0))
			.select_from(DocumentVersion)
			.join(Document, Document.id == DocumentVersion.document_id)
			.join(
				Ownership,
				(Ownership.resource_id == Document.id)
				& (Ownership.owner_type == "user")
				& (Ownership.resource_type == "node"),
			)
			.join(User, User.id == Ownership.owner_id)
			.where(User.tenant_id == tenant_id)
		)
		total_bytes = await db.scalar(stmt) or 0
		return round(total_bytes / (1024 * 1024), 2)
	except Exception:
		return 0.0


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/system-stats")
async def get_system_stats(
	user=Depends(_require_superuser),
	db: AsyncSession = Depends(get_db),
) -> SystemStats:
	"""Global platform statistics — counts across all tenants."""
	from papermerge.core.features.tenants.db.orm import Tenant
	from papermerge.core.features.users.db.orm import User
	from papermerge.core.features.document.db.orm import Document, DocumentVersion
	from papermerge.core.features.ownership.db.orm import Ownership

	today_start = datetime.now(timezone.utc).replace(
		hour=0, minute=0, second=0, microsecond=0
	)

	total_tenants = await db.scalar(select(func.count()).select_from(Tenant)) or 0
	total_users = await db.scalar(select(func.count()).select_from(User)) or 0

	# Documents = nodes of type document; use Document ORM directly
	total_documents = await db.scalar(select(func.count()).select_from(Document)) or 0

	# Storage: sum of all DocumentVersion sizes
	storage_bytes = await db.scalar(
		select(func.coalesce(func.sum(DocumentVersion.size), 0)).select_from(DocumentVersion)
	) or 0
	total_storage_gb = round(storage_bytes / (1024 ** 3), 3)

	# New documents today
	documents_today = await db.scalar(
		select(func.count())
		.select_from(Document)
		.where(Document.created_at >= today_start)
	) or 0

	# New users today — guard for missing created_at column
	try:
		new_users_today = await db.scalar(
			select(func.count())
			.select_from(User)
			.where(User.created_at >= today_start)
		) or 0
	except Exception:
		new_users_today = 0

	return SystemStats(
		total_tenants=total_tenants,
		total_users=total_users,
		total_documents=total_documents,
		total_storage_gb=total_storage_gb,
		documents_today=documents_today,
		new_users_today=new_users_today,
	)


@router.get("/tenants")
async def list_tenants(
	user=Depends(_require_superuser),
	db: AsyncSession = Depends(get_db),
	page: int = 1,
	page_size: int = 50,
) -> list[TenantStats]:
	"""List all tenants with per-tenant stats for the admin table."""
	from papermerge.core.features.tenants.db.orm import Tenant

	offset = (page - 1) * page_size
	stmt = select(Tenant).order_by(Tenant.name).offset(offset).limit(page_size)
	result = await db.execute(stmt)
	tenants = result.scalars().all()

	out: list[TenantStats] = []
	for t in tenants:
		user_count = await _tenant_user_count(db, t.id)
		doc_count = await _tenant_doc_count(db, t.id)
		storage_mb = await _tenant_storage_mb(db, t.id)
		out.append(TenantStats(
			id=str(t.id),
			name=t.name,
			slug=t.slug,
			is_active=(t.status == "active"),
			plan=t.plan,
			user_count=user_count,
			document_count=doc_count,
			storage_mb=storage_mb,
			created_at=t.created_at,
		))

	return out


@router.get("/tenants/{tenant_id}")
async def get_tenant(
	tenant_id: UUID,
	user=Depends(_require_superuser),
	db: AsyncSession = Depends(get_db),
) -> TenantDetail:
	"""Retrieve full tenant detail + recent activity for the edit dialog."""
	from papermerge.core.features.tenants.db.orm import Tenant

	tenant = await db.get(Tenant, tenant_id)
	if not tenant:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

	user_count = await _tenant_user_count(db, tenant.id)
	doc_count = await _tenant_doc_count(db, tenant.id)
	storage_mb = await _tenant_storage_mb(db, tenant.id)

	# Build recent activity from audit log if available, otherwise empty list
	recent_activity: list[TenantActivity] = []
	try:
		from papermerge.core.features.audit.db.orm import AuditLog
		from papermerge.core.features.users.db.orm import User as UserORM
		stmt = (
			select(AuditLog)
			.join(UserORM, UserORM.id == AuditLog.user_id)
			.where(UserORM.tenant_id == tenant_id)
			.order_by(AuditLog.created_at.desc())
			.limit(10)
		)
		result = await db.execute(stmt)
		logs = result.scalars().all()
		for log in logs:
			recent_activity.append(TenantActivity(
				timestamp=log.created_at,
				description=f"{log.verb} {log.object_type or ''}".strip(),
			))
	except Exception as exc:
		logger.debug("Could not fetch audit log for tenant %s: %s", tenant_id, exc)

	return TenantDetail(
		id=str(tenant.id),
		name=tenant.name,
		slug=tenant.slug,
		is_active=(tenant.status == "active"),
		plan=tenant.plan,
		contact_email=tenant.contact_email,
		max_users=tenant.max_users,
		max_storage_gb=tenant.max_storage_gb,
		features=tenant.features,
		user_count=user_count,
		document_count=doc_count,
		storage_mb=storage_mb,
		created_at=tenant.created_at,
		recent_activity=recent_activity,
	)


@router.patch("/tenants/{tenant_id}")
async def patch_tenant(
	tenant_id: UUID,
	body: TenantPatchRequest,
	user=Depends(_require_superuser),
	db: AsyncSession = Depends(get_db),
) -> TenantDetail:
	"""Update tenant active status, storage quota, or feature flags."""
	from papermerge.core.features.tenants.db.orm import Tenant

	tenant = await db.get(Tenant, tenant_id)
	if not tenant:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

	if body.is_active is not None:
		tenant.status = "active" if body.is_active else "suspended"

	if body.storage_quota_gb is not None:
		tenant.max_storage_gb = int(body.storage_quota_gb)
		# Keep TenantSettings in sync if it exists
		try:
			from papermerge.core.features.tenants.db.orm import TenantSettings
			from sqlalchemy import select as sa_select
			stmt = sa_select(TenantSettings).where(TenantSettings.tenant_id == tenant_id)
			result = await db.execute(stmt)
			ts = result.scalar()
			if ts:
				ts.storage_quota_gb = int(body.storage_quota_gb)
		except Exception:
			pass

	if body.feature_flags is not None:
		# Merge with existing features dict
		existing = tenant.features or {}
		existing.update(body.feature_flags)
		tenant.features = existing

	await db.commit()
	await db.refresh(tenant)

	# Return updated detail
	return await get_tenant(tenant_id, user, db)


@router.post("/tenants", status_code=status.HTTP_201_CREATED)
async def create_tenant(
	body: CreateTenantRequest,
	user=Depends(_require_superuser),
	db: AsyncSession = Depends(get_db),
) -> TenantDetail:
	"""Create a new tenant from the super-admin panel."""
	from papermerge.core.features.tenants.db.orm import Tenant, TenantBranding, TenantSettings

	# Slug uniqueness check
	stmt = select(Tenant).where(Tenant.slug == body.slug)
	if await db.scalar(stmt):
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Slug already exists")

	tenant = Tenant(
		name=body.name,
		slug=body.slug,
		plan=body.plan,
		contact_email=body.contact_email,
		max_users=body.max_users,
		max_storage_gb=body.max_storage_gb,
		status="active",
	)
	db.add(tenant)
	await db.flush()

	db.add(TenantBranding(tenant_id=tenant.id))
	db.add(TenantSettings(tenant_id=tenant.id))

	await db.commit()
	await db.refresh(tenant)

	return await get_tenant(tenant.id, user, db)
