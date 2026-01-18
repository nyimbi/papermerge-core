# (c) Copyright Datacraft, 2026
"""Encryption and hidden document access API endpoints."""
import logging
from uuid import UUID
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from papermerge.core.services.encryption import EncryptionService
from papermerge.core.services.single_view import SingleViewService
from papermerge.core.utils.tz import utc_now
from . import schema
from .db.orm import KeyEncryptionKey, HiddenDocumentAccess, AccessRequestStatus

router = APIRouter(
	prefix="/encryption",
	tags=["encryption"],
)

logger = logging.getLogger(__name__)


@router.get("/keys")
async def list_encryption_keys(
	user: require_scopes(scopes.TENANT_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> schema.KeyListResponse:
	"""List encryption keys for tenant."""
	stmt = select(KeyEncryptionKey).where(
		KeyEncryptionKey.tenant_id == user.tenant_id
	).order_by(KeyEncryptionKey.key_version.desc())
	result = await db_session.execute(stmt)
	keys = result.scalars().all()

	active_version = 0
	for key in keys:
		if key.is_active:
			active_version = key.key_version
			break

	return schema.KeyListResponse(
		items=[schema.KeyInfo.model_validate(k) for k in keys],
		active_version=active_version,
	)


@router.post("/keys/rotate")
async def rotate_encryption_key(
	request: schema.RotateKeyRequest,
	user: require_scopes(scopes.TENANT_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> schema.RotateKeyResponse:
	"""Rotate the tenant's encryption key."""
	service = EncryptionService(db_session)

	try:
		new_kek = await service.rotate_tenant_key(
			tenant_id=user.tenant_id,
			expire_old_in_days=request.expire_old_in_days,
		)
		return schema.RotateKeyResponse(
			success=True,
			new_version=new_kek.key_version,
			message="Key rotated successfully",
		)
	except ValueError as e:
		raise HTTPException(status_code=400, detail=str(e))


@router.get("/documents/{document_id}")
async def get_document_encryption_info(
	document_id: UUID,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.DocumentEncryptionInfo:
	"""Get encryption information for a document."""
	from .db.orm import DocumentEncryptionKey

	stmt = select(DocumentEncryptionKey).where(
		DocumentEncryptionKey.document_id == document_id
	).order_by(DocumentEncryptionKey.key_version.desc())
	result = await db_session.execute(stmt)
	dek = result.scalar()

	if dek:
		return schema.DocumentEncryptionInfo(
			document_id=document_id,
			is_encrypted=True,
			key_version=dek.key_version,
			algorithm=dek.key_algorithm,
			created_at=dek.created_at,
		)

	return schema.DocumentEncryptionInfo(
		document_id=document_id,
		is_encrypted=False,
	)


@router.post("/hidden-access/request")
async def request_hidden_document_access(
	request: schema.HiddenAccessRequest,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.HiddenAccessInfo:
	"""Request access to a hidden document."""
	access_request = HiddenDocumentAccess(
		document_id=request.document_id,
		requested_by=user.id,
		reason=request.reason,
		status=AccessRequestStatus.PENDING.value,
	)
	db_session.add(access_request)
	await db_session.commit()
	await db_session.refresh(access_request)

	return schema.HiddenAccessInfo.model_validate(access_request)


@router.get("/hidden-access/pending")
async def list_pending_access_requests(
	user: require_scopes(scopes.TENANT_ADMIN),
	db_session: AsyncSession = Depends(get_db),
	page: int = 1,
	page_size: int = 50,
) -> schema.HiddenAccessListResponse:
	"""List pending hidden document access requests."""
	offset = (page - 1) * page_size

	conditions = [HiddenDocumentAccess.status == AccessRequestStatus.PENDING.value]

	count_stmt = select(func.count()).select_from(HiddenDocumentAccess).where(and_(*conditions))
	total = await db_session.scalar(count_stmt)

	stmt = select(HiddenDocumentAccess).where(
		and_(*conditions)
	).order_by(HiddenDocumentAccess.requested_at.desc()).offset(offset).limit(page_size)
	result = await db_session.execute(stmt)
	requests = result.scalars().all()

	return schema.HiddenAccessListResponse(
		items=[schema.HiddenAccessInfo.model_validate(r) for r in requests],
		total=total,
		page=page,
		page_size=page_size,
	)


@router.post("/hidden-access/{request_id}/approve")
async def approve_hidden_access(
	request_id: UUID,
	approval: schema.ApproveAccessRequest,
	user: require_scopes(scopes.TENANT_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> schema.HiddenAccessInfo:
	"""Approve a hidden document access request."""
	access_request = await db_session.get(HiddenDocumentAccess, request_id)
	if not access_request:
		raise HTTPException(status_code=404, detail="Access request not found")

	if access_request.status != AccessRequestStatus.PENDING.value:
		raise HTTPException(status_code=400, detail="Request already processed")

	access_request.status = AccessRequestStatus.APPROVED.value
	access_request.approved_by = user.id
	access_request.approved_at = utc_now()
	access_request.expires_at = utc_now() + timedelta(hours=approval.duration_hours)

	await db_session.commit()
	await db_session.refresh(access_request)

	return schema.HiddenAccessInfo.model_validate(access_request)


@router.post("/hidden-access/{request_id}/deny")
async def deny_hidden_access(
	request_id: UUID,
	user: require_scopes(scopes.TENANT_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> schema.HiddenAccessInfo:
	"""Deny a hidden document access request."""
	access_request = await db_session.get(HiddenDocumentAccess, request_id)
	if not access_request:
		raise HTTPException(status_code=404, detail="Access request not found")

	if access_request.status != AccessRequestStatus.PENDING.value:
		raise HTTPException(status_code=400, detail="Request already processed")

	access_request.status = AccessRequestStatus.DENIED.value
	access_request.approved_by = user.id
	access_request.approved_at = utc_now()

	await db_session.commit()
	await db_session.refresh(access_request)

	return schema.HiddenAccessInfo.model_validate(access_request)


@router.post("/single-view")
async def create_single_view_access(
	request: schema.HiddenAccessRequest,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.SingleViewAccessResponse:
	"""Create single-view access token for a hidden document."""
	service = SingleViewService(db_session)

	try:
		result = await service.create_single_view_access(
			document_id=request.document_id,
			created_by=user.id,
			reason=request.reason,
			expires_in_hours=request.duration_hours,
		)
		return schema.SingleViewAccessResponse(
			access_token=result.access_token,
			expires_at=result.expires_at,
			document_id=result.document_id,
		)
	except ValueError as e:
		raise HTTPException(status_code=400, detail=str(e))


@router.post("/single-view/validate")
async def validate_single_view_access(
	request: schema.ValidateAccessRequest,
	db_session: AsyncSession = Depends(get_db),
) -> schema.ValidateAccessResponse:
	"""Validate a single-view access token."""
	service = SingleViewService(db_session)

	result = await service.validate_access(request.access_token)

	if result:
		return schema.ValidateAccessResponse(
			valid=True,
			document_id=result.document_id,
			expires_at=result.expires_at,
			view_count=result.view_count,
			max_views=result.max_views,
		)

	return schema.ValidateAccessResponse(valid=False)
