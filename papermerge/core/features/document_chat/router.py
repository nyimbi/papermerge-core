"""Document Q&A router — auto-discovered by router_loader."""
import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import scopes
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.document_chat.db.orm import DocumentChatMessage
from papermerge.core.features.document_chat.service import (
	chat_with_document,
	get_conversation_history,
	clear_conversation,
)

logger = logging.getLogger(__name__)

router = APIRouter(
	prefix="/documents",
	tags=["document-chat"],
)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
	question: str
	conversation_id: Optional[str] = None


class ChatResponse(BaseModel):
	answer: str
	conversation_id: str
	message_id: str
	page_references: list[int] = []


class MessageOut(BaseModel):
	id: str
	conversation_id: str
	document_id: str
	role: str
	content: str
	page_references: list[int] = []
	created_at: str

	model_config = {"from_attributes": True}


class ConversationHistoryResponse(BaseModel):
	conversation_id: str
	messages: list[MessageOut]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
	"/{document_id}/chat",
	response_model=ChatResponse,
	summary="Ask a question about a document",
)
async def post_chat(
	document_id: str,
	body: ChatRequest,
	user: Annotated[object, Depends(require_scopes(scopes.NODE_VIEW))],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ChatResponse:
	try:
		result = await chat_with_document(
			document_id=document_id,
			question=body.question,
			conversation_id=body.conversation_id,
			user_id=str(user.id),
			tenant_id=str(getattr(user, "tenant_id", user.id)),
			session=session,
		)
	except Exception as exc:
		logger.error("chat_with_document failed: %s", exc)
		raise HTTPException(
			status_code=status.HTTP_502_BAD_GATEWAY,
			detail=f"LLM service error: {exc}",
		)
	return ChatResponse(**result)


@router.get(
	"/{document_id}/chat/{conversation_id}",
	response_model=ConversationHistoryResponse,
	summary="Get conversation history for a document",
)
async def get_chat_history(
	document_id: str,
	conversation_id: str,
	user: Annotated[object, Depends(require_scopes(scopes.NODE_VIEW))],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ConversationHistoryResponse:
	messages = await get_conversation_history(
		conversation_id=conversation_id,
		limit=100,
		session=session,
	)
	# Filter to this document
	messages = [m for m in messages if m.document_id == document_id]

	import json
	msg_out = []
	for m in messages:
		try:
			page_refs = json.loads(m.page_references or "[]")
		except Exception:
			page_refs = []
		msg_out.append(
			MessageOut(
				id=m.id,
				conversation_id=m.conversation_id,
				document_id=m.document_id,
				role=m.role,
				content=m.content,
				page_references=page_refs,
				created_at=m.created_at.isoformat() if m.created_at else "",
			)
		)
	return ConversationHistoryResponse(
		conversation_id=conversation_id,
		messages=msg_out,
	)


@router.delete(
	"/{document_id}/chat/{conversation_id}",
	status_code=status.HTTP_204_NO_CONTENT,
	summary="Clear a conversation",
)
async def delete_chat_conversation(
	document_id: str,
	conversation_id: str,
	user: Annotated[object, Depends(require_scopes(scopes.NODE_UPDATE))],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
	await clear_conversation(conversation_id=conversation_id, session=session)
