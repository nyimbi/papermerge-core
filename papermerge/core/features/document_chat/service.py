"""Document Q&A service — fetch OCR text and chat via LiteLLM (qwen2.5-VL)."""
import json
import logging
import uuid
from datetime import datetime

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.features.document_chat.db.orm import DocumentChatMessage
from papermerge.core.utils.tz import utc_now

logger = logging.getLogger(__name__)

LITELLM_BASE_URL = "http://84.247.181.100:4000/v1"
LITELLM_API_KEY = "sk-pjs-litellm-master-key"
LITELLM_MODEL = "qwen2.5-VL"


async def get_document_text(document_id: str, session: AsyncSession) -> str:
	"""Fetch OCR text from the latest document version's pages, in page order."""
	from sqlalchemy import text as sa_text

	# Get the latest version's pages ordered by page number
	sql = sa_text("""
		SELECT p.text, p.number
		FROM pages p
		JOIN document_versions dv ON p.document_version_id = dv.id
		WHERE dv.document_id = :doc_id
		  AND p.text IS NOT NULL
		  AND p.text != ''
		ORDER BY dv.number DESC, p.number ASC
		LIMIT 500
	""")
	result = await session.execute(sql, {"doc_id": document_id})
	rows = result.fetchall()

	if not rows:
		return ""

	# Collect text from the latest version (first rows with same version number)
	# The query returns newest version first; take all pages from the latest version
	full_text = "\n\n".join(row.text for row in rows if row.text)

	# Truncate to 8000 chars: first 4000 + last 4000
	if len(full_text) > 8000:
		full_text = full_text[:4000] + "\n\n[... content truncated ...]\n\n" + full_text[-4000:]

	return full_text


async def get_conversation_history(
	conversation_id: str,
	limit: int,
	session: AsyncSession,
) -> list[DocumentChatMessage]:
	stmt = (
		select(DocumentChatMessage)
		.where(DocumentChatMessage.conversation_id == conversation_id)
		.order_by(DocumentChatMessage.created_at.asc())
		.limit(limit)
	)
	result = await session.execute(stmt)
	return list(result.scalars().all())


async def chat_with_document(
	document_id: str,
	question: str,
	conversation_id: str | None,
	user_id: str,
	tenant_id: str,
	session: AsyncSession,
) -> dict:
	"""Run a Q&A turn against a document using LiteLLM."""
	import openai  # openai SDK, pointed at LiteLLM proxy

	if not conversation_id:
		conversation_id = str(uuid.uuid4())

	# 1. Get document OCR text
	doc_text = await get_document_text(document_id, session)
	if not doc_text:
		doc_text = "(No OCR text available for this document.)"

	# 2. Fetch last 5 messages for context
	history = await get_conversation_history(conversation_id, limit=10, session=session)
	# take last 5 turns (10 messages max, already ordered asc)
	history = history[-10:]

	# 3. Build messages list
	messages: list[dict] = [
		{
			"role": "system",
			"content": (
				"You are a helpful assistant that answers questions about documents. "
				"Be concise. When referencing specific parts, mention the approximate "
				"location (beginning/middle/end of the document)."
			),
		},
		{
			"role": "system",
			"content": f"Document content:\n\n{doc_text}",
		},
	]

	for msg in history:
		messages.append({"role": msg.role, "content": msg.content})

	messages.append({"role": "user", "content": question})

	# 4. Call LiteLLM
	client = openai.OpenAI(base_url=LITELLM_BASE_URL, api_key=LITELLM_API_KEY)
	try:
		resp = client.chat.completions.create(
			model=LITELLM_MODEL,
			messages=messages,
			max_tokens=500,
		)
		answer = resp.choices[0].message.content or ""
	except Exception as exc:
		logger.error("LiteLLM call failed for document %s: %s", document_id, exc)
		raise

	# 5. Save user message
	user_msg = DocumentChatMessage(
		id=str(uuid.uuid4()),
		conversation_id=conversation_id,
		document_id=document_id,
		role="user",
		content=question,
		page_references="[]",
		created_by_id=user_id,
		tenant_id=tenant_id,
		created_at=utc_now(),
	)
	session.add(user_msg)

	# Save assistant message
	assistant_msg_id = str(uuid.uuid4())
	assistant_msg = DocumentChatMessage(
		id=assistant_msg_id,
		conversation_id=conversation_id,
		document_id=document_id,
		role="assistant",
		content=answer,
		page_references="[]",
		created_by_id=user_id,
		tenant_id=tenant_id,
		created_at=utc_now(),
	)
	session.add(assistant_msg)
	await session.commit()

	return {
		"answer": answer,
		"conversation_id": conversation_id,
		"message_id": assistant_msg_id,
		"page_references": [],
	}


async def clear_conversation(conversation_id: str, session: AsyncSession) -> None:
	stmt = delete(DocumentChatMessage).where(
		DocumentChatMessage.conversation_id == conversation_id
	)
	await session.execute(stmt)
	await session.commit()
