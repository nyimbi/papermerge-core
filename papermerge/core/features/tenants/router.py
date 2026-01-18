# (c) Copyright Datacraft, 2026
"""Tenant management API endpoints."""
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from . import schema
from .db.orm import Tenant, TenantBranding, TenantSettings

router = APIRouter(
	prefix="/tenants",
	tags=["tenants"],
)

logger = logging.getLogger(__name__)


@router.get("/current")
async def get_current_tenant(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.TenantDetail:
	"""Get current user's tenant details."""
	tenant = await db_session.get(Tenant, user.tenant_id)
	if not tenant:
		raise HTTPException(status_code=404, detail="Tenant not found")

	result = schema.TenantDetail(
		id=tenant.id,
		name=tenant.name,
		slug=tenant.slug,
		status=tenant.status,
		contact_email=tenant.contact_email,
		contact_phone=tenant.contact_phone,
		billing_email=tenant.billing_email,
		stripe_customer_id=tenant.stripe_customer_id,
		max_users=tenant.max_users,
		max_storage_gb=tenant.max_storage_gb,
		trial_ends_at=tenant.trial_ends_at,
		created_at=tenant.created_at,
		updated_at=tenant.updated_at,
	)

	if tenant.branding:
		result.branding = schema.TenantBrandingInfo.model_validate(tenant.branding)
	if tenant.settings:
		result.settings = schema.TenantSettingsInfo.model_validate(tenant.settings)

	return result


@router.patch("/current")
async def update_current_tenant(
	updates: schema.TenantUpdate,
	user: require_scopes(scopes.TENANT_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> schema.TenantDetail:
	"""Update current tenant."""
	tenant = await db_session.get(Tenant, user.tenant_id)
	if not tenant:
		raise HTTPException(status_code=404, detail="Tenant not found")

	update_data = updates.model_dump(exclude_unset=True)
	for field, value in update_data.items():
		setattr(tenant, field, value)

	await db_session.commit()
	await db_session.refresh(tenant)

	return schema.TenantDetail(
		id=tenant.id,
		name=tenant.name,
		slug=tenant.slug,
		status=tenant.status,
		contact_email=tenant.contact_email,
		contact_phone=tenant.contact_phone,
		billing_email=tenant.billing_email,
		stripe_customer_id=tenant.stripe_customer_id,
		max_users=tenant.max_users,
		max_storage_gb=tenant.max_storage_gb,
		trial_ends_at=tenant.trial_ends_at,
		created_at=tenant.created_at,
		updated_at=tenant.updated_at,
	)


@router.get("/current/branding")
async def get_tenant_branding(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.TenantBrandingInfo:
	"""Get tenant branding settings."""
	stmt = select(TenantBranding).where(TenantBranding.tenant_id == user.tenant_id)
	result = await db_session.execute(stmt)
	branding = result.scalar()

	if branding:
		return schema.TenantBrandingInfo.model_validate(branding)

	return schema.TenantBrandingInfo()


@router.patch("/current/branding")
async def update_tenant_branding(
	updates: schema.BrandingUpdate,
	user: require_scopes(scopes.TENANT_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> schema.TenantBrandingInfo:
	"""Update tenant branding."""
	stmt = select(TenantBranding).where(TenantBranding.tenant_id == user.tenant_id)
	result = await db_session.execute(stmt)
	branding = result.scalar()

	if not branding:
		branding = TenantBranding(tenant_id=user.tenant_id)
		db_session.add(branding)

	update_data = updates.model_dump(exclude_unset=True)
	for field, value in update_data.items():
		setattr(branding, field, value)

	await db_session.commit()
	await db_session.refresh(branding)

	return schema.TenantBrandingInfo.model_validate(branding)


@router.get("/current/settings")
async def get_tenant_settings(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.TenantSettingsInfo:
	"""Get tenant settings."""
	stmt = select(TenantSettings).where(TenantSettings.tenant_id == user.tenant_id)
	result = await db_session.execute(stmt)
	settings = result.scalar()

	if settings:
		return schema.TenantSettingsInfo.model_validate(settings)

	return schema.TenantSettingsInfo()


@router.patch("/current/settings")
async def update_tenant_settings(
	updates: schema.SettingsUpdate,
	user: require_scopes(scopes.TENANT_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> schema.TenantSettingsInfo:
	"""Update tenant settings."""
	stmt = select(TenantSettings).where(TenantSettings.tenant_id == user.tenant_id)
	result = await db_session.execute(stmt)
	settings = result.scalar()

	if not settings:
		settings = TenantSettings(tenant_id=user.tenant_id)
		db_session.add(settings)

	update_data = updates.model_dump(exclude_unset=True)
	for field, value in update_data.items():
		setattr(settings, field, value)

	await db_session.commit()
	await db_session.refresh(settings)

	return schema.TenantSettingsInfo.model_validate(settings)


@router.get("/current/usage")
async def get_tenant_usage(
	user: require_scopes(scopes.TENANT_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> schema.TenantUsageInfo:
	"""Get tenant usage statistics."""
	from papermerge.core.features.users.db.orm import User
	from papermerge.core.features.document.db.orm import Document

	# Count users
	user_count_stmt = select(func.count()).select_from(User).where(
		User.tenant_id == user.tenant_id
	)
	total_users = await db_session.scalar(user_count_stmt) or 0

	# Count documents
	doc_count_stmt = select(func.count()).select_from(Document).where(
		Document.tenant_id == user.tenant_id
	)
	total_documents = await db_session.scalar(doc_count_stmt) or 0

	# Get storage used (sum of document sizes)
	storage_stmt = select(func.coalesce(func.sum(Document.file_size), 0)).where(
		Document.tenant_id == user.tenant_id
	)
	storage_used = await db_session.scalar(storage_stmt) or 0

	# Get tenant settings for quota
	tenant = await db_session.get(Tenant, user.tenant_id)
	storage_quota_bytes = None
	storage_percentage = None

	if tenant and tenant.max_storage_gb:
		storage_quota_bytes = tenant.max_storage_gb * 1024 * 1024 * 1024
		storage_percentage = (storage_used / storage_quota_bytes * 100) if storage_quota_bytes > 0 else 0

	return schema.TenantUsageInfo(
		tenant_id=user.tenant_id,
		total_users=total_users,
		total_documents=total_documents,
		storage_used_bytes=storage_used,
		storage_quota_bytes=storage_quota_bytes,
		storage_percentage=storage_percentage,
	)


# System admin endpoints for managing all tenants
@router.get("/")
async def list_tenants(
	user: require_scopes(scopes.SYSTEM_ADMIN),
	db_session: AsyncSession = Depends(get_db),
	status_filter: str | None = None,
	page: int = 1,
	page_size: int = 50,
) -> schema.TenantListResponse:
	"""List all tenants (system admin only)."""
	offset = (page - 1) * page_size

	conditions = []
	if status_filter:
		conditions.append(Tenant.status == status_filter)

	count_stmt = select(func.count()).select_from(Tenant)
	if conditions:
		count_stmt = count_stmt.where(*conditions)
	total = await db_session.scalar(count_stmt)

	stmt = select(Tenant)
	if conditions:
		stmt = stmt.where(*conditions)
	stmt = stmt.order_by(Tenant.name).offset(offset).limit(page_size)

	result = await db_session.execute(stmt)
	tenants = result.scalars().all()

	return schema.TenantListResponse(
		items=[schema.TenantInfo.model_validate(t) for t in tenants],
		total=total,
		page=page,
		page_size=page_size,
	)


@router.post("/")
async def create_tenant(
	tenant_data: schema.TenantCreate,
	user: require_scopes(scopes.SYSTEM_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> schema.TenantDetail:
	"""Create a new tenant (system admin only)."""
	# Check if slug already exists
	stmt = select(Tenant).where(Tenant.slug == tenant_data.slug)
	result = await db_session.execute(stmt)
	if result.scalar():
		raise HTTPException(status_code=400, detail="Slug already exists")

	tenant = Tenant(
		name=tenant_data.name,
		slug=tenant_data.slug,
		contact_email=tenant_data.contact_email,
		contact_phone=tenant_data.contact_phone,
		billing_email=tenant_data.billing_email,
		max_users=tenant_data.max_users,
		max_storage_gb=tenant_data.max_storage_gb,
	)
	db_session.add(tenant)
	await db_session.flush()

	# Create default branding
	branding = TenantBranding(tenant_id=tenant.id)
	db_session.add(branding)

	# Create default settings
	settings = TenantSettings(tenant_id=tenant.id)
	db_session.add(settings)

	await db_session.commit()
	await db_session.refresh(tenant)

	return schema.TenantDetail(
		id=tenant.id,
		name=tenant.name,
		slug=tenant.slug,
		status=tenant.status,
		contact_email=tenant.contact_email,
		contact_phone=tenant.contact_phone,
		billing_email=tenant.billing_email,
		max_users=tenant.max_users,
		max_storage_gb=tenant.max_storage_gb,
		created_at=tenant.created_at,
		updated_at=tenant.updated_at,
	)


@router.get("/{tenant_id}")
async def get_tenant(
	tenant_id: UUID,
	user: require_scopes(scopes.SYSTEM_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> schema.TenantDetail:
	"""Get tenant details (system admin only)."""
	tenant = await db_session.get(Tenant, tenant_id)
	if not tenant:
		raise HTTPException(status_code=404, detail="Tenant not found")

	result = schema.TenantDetail(
		id=tenant.id,
		name=tenant.name,
		slug=tenant.slug,
		status=tenant.status,
		contact_email=tenant.contact_email,
		contact_phone=tenant.contact_phone,
		billing_email=tenant.billing_email,
		stripe_customer_id=tenant.stripe_customer_id,
		max_users=tenant.max_users,
		max_storage_gb=tenant.max_storage_gb,
		trial_ends_at=tenant.trial_ends_at,
		created_at=tenant.created_at,
		updated_at=tenant.updated_at,
	)

	if tenant.branding:
		result.branding = schema.TenantBrandingInfo.model_validate(tenant.branding)
	if tenant.settings:
		result.settings = schema.TenantSettingsInfo.model_validate(tenant.settings)

	return result


@router.patch("/{tenant_id}")
async def update_tenant(
	tenant_id: UUID,
	updates: schema.TenantUpdate,
	user: require_scopes(scopes.SYSTEM_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> schema.TenantDetail:
	"""Update a tenant (system admin only)."""
	tenant = await db_session.get(Tenant, tenant_id)
	if not tenant:
		raise HTTPException(status_code=404, detail="Tenant not found")

	update_data = updates.model_dump(exclude_unset=True)
	for field, value in update_data.items():
		setattr(tenant, field, value)

	await db_session.commit()
	await db_session.refresh(tenant)

	return schema.TenantDetail(
		id=tenant.id,
		name=tenant.name,
		slug=tenant.slug,
		status=tenant.status,
		contact_email=tenant.contact_email,
		contact_phone=tenant.contact_phone,
		billing_email=tenant.billing_email,
		stripe_customer_id=tenant.stripe_customer_id,
		max_users=tenant.max_users,
		max_storage_gb=tenant.max_storage_gb,
		trial_ends_at=tenant.trial_ends_at,
		created_at=tenant.created_at,
		updated_at=tenant.updated_at,
	)
