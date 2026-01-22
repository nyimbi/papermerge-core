# (c) Copyright Datacraft, 2026
"""Cases API endpoints."""
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from . import schema
from .db.orm import Case, CaseDocument, CaseAccess

router = APIRouter(
	prefix="/cases",
	tags=["cases"],
)

logger = logging.getLogger(__name__)


@router.get("/")
async def list_cases(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
	portfolio_id: UUID | None = None,
	status_filter: str | None = None,
	page: int = 1,
	page_size: int = 20,
) -> schema.CaseListResponse:
	"""List cases accessible to the user."""
	offset = (page - 1) * page_size

	conditions = [Case.tenant_id == user.tenant_id]
	if portfolio_id:
		conditions.append(Case.portfolio_id == portfolio_id)
	if status_filter:
		conditions.append(Case.status == status_filter)

	count_stmt = select(func.count()).select_from(Case).where(and_(*conditions))
	total = await db_session.scalar(count_stmt)

	stmt = select(Case).where(and_(*conditions)).offset(offset).limit(page_size)
	result = await db_session.execute(stmt)
	cases = result.scalars().all()

	return schema.CaseListResponse(
		items=[schema.CaseInfo.model_validate(c) for c in cases],
		total=total,
		page=page,
		page_size=page_size,
	)


@router.post("/")
async def create_case(
	case: schema.CaseCreate,
	user: require_scopes(scopes.NODE_CREATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.CaseInfo:
	"""Create a new case."""
	db_case = Case(
		tenant_id=user.tenant_id,
		portfolio_id=case.portfolio_id,
		case_number=case.case_number,
		title=case.title,
		description=case.description,
		status="open",
		case_metadata=case.metadata,
		created_by=user.id,
		updated_by=user.id,
	)
	db_session.add(db_case)
	await db_session.commit()
	await db_session.refresh(db_case)

	return schema.CaseInfo.model_validate(db_case)


@router.get("/{case_id}")
async def get_case(
	case_id: UUID,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.CaseDetail:
	"""Get case details."""
	case = await db_session.get(Case, case_id)
	if not case:
		raise HTTPException(status_code=404, detail="Case not found")

	# Get documents
	stmt = select(CaseDocument).where(CaseDocument.case_id == case_id)
	result = await db_session.execute(stmt)
	documents = result.scalars().all()

	return schema.CaseDetail(
		id=case.id,
		case_number=case.case_number,
		title=case.title,
		description=case.description,
		status=case.status,
		portfolio_id=case.portfolio_id,
		metadata=case.case_metadata,
		documents=[schema.CaseDocumentInfo.model_validate(d) for d in documents],
		created_at=case.created_at,
	)


@router.patch("/{case_id}")
async def update_case(
	case_id: UUID,
	update: schema.CaseUpdate,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.CaseInfo:
	"""Update case details."""
	case = await db_session.get(Case, case_id)
	if not case:
		raise HTTPException(status_code=404, detail="Case not found")

	if update.title is not None:
		case.title = update.title
	if update.description is not None:
		case.description = update.description
	if update.status is not None:
		case.status = update.status
	if update.metadata is not None:
		case.case_metadata = update.metadata

	case.updated_by = user.id
	await db_session.commit()
	await db_session.refresh(case)

	return schema.CaseInfo.model_validate(case)


@router.post("/{case_id}/documents")
async def add_document_to_case(
	case_id: UUID,
	request: schema.AddDocumentToCaseRequest,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.CaseDocumentInfo:
	"""Add a document to a case."""
	case = await db_session.get(Case, case_id)
	if not case:
		raise HTTPException(status_code=404, detail="Case not found")

	doc = CaseDocument(
		case_id=case_id,
		document_id=request.document_id,
		document_type=request.document_type,
		added_by=user.id,
	)
	db_session.add(doc)
	await db_session.commit()
	await db_session.refresh(doc)

	return schema.CaseDocumentInfo.model_validate(doc)


@router.post("/{case_id}/access")
async def grant_case_access(
	case_id: UUID,
	request: schema.GrantAccessRequest,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.CaseAccessInfo:
	"""Grant access to a case."""
	case = await db_session.get(Case, case_id)
	if not case:
		raise HTTPException(status_code=404, detail="Case not found")

	access = CaseAccess(
		case_id=case_id,
		subject_type=request.subject_type,
		subject_id=request.subject_id,
		allow_view=request.allow_view,
		allow_download=request.allow_download,
		allow_print=request.allow_print,
		allow_edit=request.allow_edit,
		allow_share=request.allow_share,
		valid_from=request.valid_from,
		valid_until=request.valid_until,
		granted_by=user.id,
	)
	db_session.add(access)
	await db_session.commit()
	await db_session.refresh(access)

	return schema.CaseAccessInfo.model_validate(access)


@router.get("/{case_id}/access")
async def list_case_access(
	case_id: UUID,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.CaseAccessListResponse:
	"""List access grants for a case."""
	stmt = select(CaseAccess).where(CaseAccess.case_id == case_id)
	result = await db_session.execute(stmt)
	access_list = result.scalars().all()

	return schema.CaseAccessListResponse(
		items=[schema.CaseAccessInfo.model_validate(a) for a in access_list]
	)
