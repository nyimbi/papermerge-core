# (c) Copyright Datacraft, 2026
"""Document bundles API endpoints."""
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from . import schema
from .db.orm import Bundle, BundleDocument, BundleSection

router = APIRouter(
	prefix="/bundles",
	tags=["bundles"],
)

logger = logging.getLogger(__name__)


@router.get("/")
async def list_bundles(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
	case_id: UUID | None = None,
	page: int = 1,
	page_size: int = 20,
) -> schema.BundleListResponse:
	"""List bundles, optionally filtered by case."""
	offset = (page - 1) * page_size

	conditions = [Bundle.tenant_id == user.tenant_id]
	if case_id:
		conditions.append(Bundle.case_id == case_id)

	from sqlalchemy import func, and_
	count_stmt = select(func.count()).select_from(Bundle).where(and_(*conditions))
	total = await db_session.scalar(count_stmt)

	stmt = select(Bundle).where(and_(*conditions)).offset(offset).limit(page_size)
	result = await db_session.execute(stmt)
	bundles = result.scalars().all()

	return schema.BundleListResponse(
		items=[schema.BundleInfo.model_validate(b) for b in bundles],
		total=total,
		page=page,
		page_size=page_size,
	)


@router.post("/")
async def create_bundle(
	bundle: schema.BundleCreate,
	user: require_scopes(scopes.NODE_CREATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.BundleInfo:
	"""Create a new document bundle."""
	db_bundle = Bundle(
		tenant_id=user.tenant_id,
		case_id=bundle.case_id,
		name=bundle.name,
		description=bundle.description,
		bundle_type=bundle.bundle_type,
		status="draft",
		created_by=user.id,
		updated_by=user.id,
	)
	db_session.add(db_bundle)
	await db_session.commit()
	await db_session.refresh(db_bundle)

	return schema.BundleInfo.model_validate(db_bundle)


@router.get("/{bundle_id}")
async def get_bundle(
	bundle_id: UUID,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.BundleDetail:
	"""Get bundle details with documents."""
	bundle = await db_session.get(Bundle, bundle_id)
	if not bundle:
		raise HTTPException(status_code=404, detail="Bundle not found")

	# Get documents
	stmt = select(BundleDocument).where(
		BundleDocument.bundle_id == bundle_id
	).order_by(BundleDocument.position)
	result = await db_session.execute(stmt)
	documents = result.scalars().all()

	# Get sections
	stmt = select(BundleSection).where(
		BundleSection.bundle_id == bundle_id
	).order_by(BundleSection.position)
	result = await db_session.execute(stmt)
	sections = result.scalars().all()

	return schema.BundleDetail(
		id=bundle.id,
		name=bundle.name,
		description=bundle.description,
		bundle_type=bundle.bundle_type,
		status=bundle.status,
		case_id=bundle.case_id,
		documents=[schema.BundleDocumentInfo.model_validate(d) for d in documents],
		sections=[schema.BundleSectionInfo.model_validate(s) for s in sections],
	)


@router.post("/{bundle_id}/documents")
async def add_document_to_bundle(
	bundle_id: UUID,
	request: schema.AddDocumentRequest,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.BundleDocumentInfo:
	"""Add a document to a bundle."""
	bundle = await db_session.get(Bundle, bundle_id)
	if not bundle:
		raise HTTPException(status_code=404, detail="Bundle not found")

	# Get max position
	from sqlalchemy import func
	stmt = select(func.max(BundleDocument.position)).where(
		BundleDocument.bundle_id == bundle_id
	)
	max_pos = await db_session.scalar(stmt) or 0

	doc = BundleDocument(
		bundle_id=bundle_id,
		document_id=request.document_id,
		section_id=request.section_id,
		position=max_pos + 1,
		include_in_pagination=request.include_in_pagination,
	)
	db_session.add(doc)
	await db_session.commit()
	await db_session.refresh(doc)

	return schema.BundleDocumentInfo.model_validate(doc)


@router.delete("/{bundle_id}/documents/{document_id}")
async def remove_document_from_bundle(
	bundle_id: UUID,
	document_id: UUID,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Remove a document from a bundle."""
	stmt = select(BundleDocument).where(
		BundleDocument.bundle_id == bundle_id,
		BundleDocument.document_id == document_id,
	)
	result = await db_session.execute(stmt)
	doc = result.scalar_one_or_none()

	if not doc:
		raise HTTPException(status_code=404, detail="Document not in bundle")

	await db_session.delete(doc)
	await db_session.commit()

	return {"success": True}


@router.post("/{bundle_id}/sections")
async def create_bundle_section(
	bundle_id: UUID,
	section: schema.BundleSectionCreate,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.BundleSectionInfo:
	"""Create a section in a bundle."""
	bundle = await db_session.get(Bundle, bundle_id)
	if not bundle:
		raise HTTPException(status_code=404, detail="Bundle not found")

	from sqlalchemy import func
	stmt = select(func.max(BundleSection.position)).where(
		BundleSection.bundle_id == bundle_id
	)
	max_pos = await db_session.scalar(stmt) or 0

	db_section = BundleSection(
		bundle_id=bundle_id,
		name=section.name,
		position=max_pos + 1,
	)
	db_session.add(db_section)
	await db_session.commit()
	await db_session.refresh(db_section)

	return schema.BundleSectionInfo.model_validate(db_section)


@router.post("/{bundle_id}/paginate")
async def generate_pagination(
	bundle_id: UUID,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.PaginationResult:
	"""Generate pagination for bundle documents."""
	bundle = await db_session.get(Bundle, bundle_id)
	if not bundle:
		raise HTTPException(status_code=404, detail="Bundle not found")

	from papermerge.core.features.document.db.orm import Document, DocumentVersion

	# Get documents that should be paginated
	stmt = select(BundleDocument).where(
		BundleDocument.bundle_id == bundle_id,
		BundleDocument.include_in_pagination == True,
	).order_by(BundleDocument.position)
	result = await db_session.execute(stmt)
	bundle_docs = result.scalars().all()

	# Calculate pagination using actual page counts
	current_page = 1
	for bundle_doc in bundle_docs:
		# Get the document's latest version to determine page count
		doc_result = await db_session.execute(
			select(Document).where(Document.id == bundle_doc.document_id)
		)
		document = doc_result.scalar_one_or_none()

		page_count = 0
		if document:
			# Get latest document version for page count
			ver_result = await db_session.execute(
				select(DocumentVersion)
				.where(DocumentVersion.document_id == document.id)
				.order_by(DocumentVersion.number.desc())
				.limit(1)
			)
			version = ver_result.scalar_one_or_none()

			if version:
				# If partial inclusion, use specified range
				if bundle_doc.start_page is not None and bundle_doc.end_page is not None:
					page_count = bundle_doc.end_page - bundle_doc.start_page + 1
				else:
					# Use the page_count from document version
					page_count = version.page_count if hasattr(version, 'page_count') else len(version.pages)

		# Set pagination values
		bundle_doc.bundle_page_start = current_page
		bundle_doc.bundle_page_end = current_page + max(page_count - 1, 0)
		current_page = bundle_doc.bundle_page_end + 1

	await db_session.commit()

	return schema.PaginationResult(
		total_pages=current_page - 1,
		document_count=len(bundle_docs),
	)
