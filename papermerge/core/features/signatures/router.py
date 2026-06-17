"""
Digital signature workflow router.

Endpoints:
  POST /documents/{document_id}/signature-requests   — request a signature
  GET  /documents/{document_id}/signature-requests   — list requests
  POST /signature-requests/{id}/sign                 — sign with drawn signature
  POST /signature-requests/{id}/decline              — decline a request
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import scopes
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.signatures.db.orm import DocumentSignatureRequest
from papermerge.core.features.signatures.service import apply_signature_to_document

logger = logging.getLogger(__name__)

router = APIRouter(tags=["signatures"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class SignatureRequestOut(BaseModel):
	id: uuid.UUID
	document_id: str
	requested_from_email: str
	requested_from_name: str
	requested_by_id: str
	status: str
	signed_at: Optional[datetime]
	declined_at: Optional[datetime]
	decline_reason: Optional[str]
	signature_page: int
	signature_x: float
	signature_y: float
	signature_width: float
	signature_height: float
	signed_document_id: Optional[str]
	tenant_id: str
	created_at: datetime

	model_config = {"from_attributes": True}


class CreateSignatureRequestBody(BaseModel):
	requested_from_email: EmailStr
	requested_from_name: str = ""
	signature_page: int = Field(default=1, ge=1)
	signature_x: float = Field(default=0.7, ge=0.0, le=1.0)
	signature_y: float = Field(default=0.85, ge=0.0, le=1.0)
	signature_width: float = Field(default=0.25, ge=0.0, le=1.0)
	signature_height: float = Field(default=0.1, ge=0.0, le=1.0)


class SignBody(BaseModel):
	signature_data: str  # base64-encoded PNG


class DeclineBody(BaseModel):
	reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post(
	"/documents/{document_id}/signature-requests",
	response_model=SignatureRequestOut,
	status_code=status.HTTP_201_CREATED,
	summary="Request a signature on a document",
)
async def create_signature_request(
	document_id: str,
	body: CreateSignatureRequestBody,
	user: Annotated[object, Depends(require_scopes(scopes.NODE_UPDATE))],
	db_session: AsyncSession = Depends(get_db),
) -> SignatureRequestOut:
	req = DocumentSignatureRequest(
		document_id=document_id,
		requested_from_email=body.requested_from_email,
		requested_from_name=body.requested_from_name,
		requested_by_id=str(user.id),
		status="pending",
		signature_page=body.signature_page,
		signature_x=body.signature_x,
		signature_y=body.signature_y,
		signature_width=body.signature_width,
		signature_height=body.signature_height,
		tenant_id=str(getattr(user, "tenant_id", user.id)),
	)
	db_session.add(req)
	try:
		await db_session.commit()
		await db_session.refresh(req)
	except Exception as exc:
		await db_session.rollback()
		logger.error("Failed to create signature request: %s", exc, exc_info=True)
		raise HTTPException(status_code=500, detail="Failed to create signature request")

	return SignatureRequestOut.model_validate(req)


@router.get(
	"/documents/{document_id}/signature-requests",
	response_model=list[SignatureRequestOut],
	summary="List signature requests for a document",
)
async def list_signature_requests(
	document_id: str,
	user: Annotated[object, Depends(require_scopes(scopes.NODE_VIEW))],
	db_session: AsyncSession = Depends(get_db),
) -> list[SignatureRequestOut]:
	stmt = (
		select(DocumentSignatureRequest)
		.where(DocumentSignatureRequest.document_id == document_id)
		.order_by(DocumentSignatureRequest.created_at)
	)
	result = await db_session.execute(stmt)
	rows = result.scalars().all()
	return [SignatureRequestOut.model_validate(r) for r in rows]


@router.post(
	"/signature-requests/{request_id}/sign",
	response_model=SignatureRequestOut,
	summary="Sign a document with a drawn signature",
)
async def sign_document(
	request_id: uuid.UUID,
	body: SignBody,
	user: Annotated[object, Depends(require_scopes(scopes.NODE_UPDATE))],
	db_session: AsyncSession = Depends(get_db),
) -> SignatureRequestOut:
	result = await db_session.execute(
		select(DocumentSignatureRequest).where(
			DocumentSignatureRequest.id == request_id
		)
	)
	req = result.scalar_one_or_none()
	if req is None:
		raise HTTPException(status_code=404, detail="Signature request not found")
	if req.status != "pending":
		raise HTTPException(
			status_code=409,
			detail=f"Request is already {req.status}",
		)

	# Stamp signature onto document
	try:
		new_doc_id = await apply_signature_to_document(
			doc_id=req.document_id,
			page_num=req.signature_page,
			sig_data_b64=body.signature_data,
			x=req.signature_x,
			y=req.signature_y,
			w=req.signature_width,
			h=req.signature_height,
			session=db_session,
		)
	except FileNotFoundError as exc:
		logger.warning("Document not found for signing: %s", exc)
		# Still mark as signed even if PDF stamping fails (doc may be remote/
		# not on this node); store signature data for downstream processing.
		new_doc_id = None
	except Exception as exc:
		logger.error("Failed to stamp signature: %s", exc, exc_info=True)
		raise HTTPException(status_code=500, detail="Failed to apply signature to document")

	req.status = "signed"
	req.signed_at = datetime.now(timezone.utc)
	req.signature_data = body.signature_data
	req.signed_document_id = new_doc_id

	try:
		await db_session.commit()
		await db_session.refresh(req)
	except Exception as exc:
		await db_session.rollback()
		logger.error("Failed to save signed status: %s", exc, exc_info=True)
		raise HTTPException(status_code=500, detail="Failed to save signed status")

	return SignatureRequestOut.model_validate(req)


@router.post(
	"/signature-requests/{request_id}/decline",
	response_model=SignatureRequestOut,
	summary="Decline a signature request",
)
async def decline_signature_request(
	request_id: uuid.UUID,
	body: DeclineBody,
	user: Annotated[object, Depends(require_scopes(scopes.NODE_UPDATE))],
	db_session: AsyncSession = Depends(get_db),
) -> SignatureRequestOut:
	result = await db_session.execute(
		select(DocumentSignatureRequest).where(
			DocumentSignatureRequest.id == request_id
		)
	)
	req = result.scalar_one_or_none()
	if req is None:
		raise HTTPException(status_code=404, detail="Signature request not found")
	if req.status != "pending":
		raise HTTPException(
			status_code=409,
			detail=f"Request is already {req.status}",
		)

	req.status = "declined"
	req.declined_at = datetime.now(timezone.utc)
	req.decline_reason = body.reason

	try:
		await db_session.commit()
		await db_session.refresh(req)
	except Exception as exc:
		await db_session.rollback()
		logger.error("Failed to save declined status: %s", exc, exc_info=True)
		raise HTTPException(status_code=500, detail="Failed to decline signature request")

	return SignatureRequestOut.model_validate(req)
