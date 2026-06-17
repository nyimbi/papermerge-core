"""
Smart Duplicate Detection service.

Computes file-level and content-level SHA-256 hashes for documents,
stores them in document_hashes, and exposes duplicate-finding queries.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.features.dedup.db.orm import DocumentHash
from papermerge.core.utils.uuid_compat import uuid7str

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hash helpers
# ---------------------------------------------------------------------------

def compute_file_hash(file_bytes: bytes) -> str:
	"""SHA-256 of raw file bytes."""
	return hashlib.sha256(file_bytes).hexdigest()


def compute_text_hash(text_content: str) -> str:
	"""SHA-256 of normalised (lowercased, collapsed-whitespace) extracted text."""
	normalised = " ".join(text_content.lower().split())
	return hashlib.sha256(normalised.encode()).hexdigest()


# ---------------------------------------------------------------------------
# DB operations
# ---------------------------------------------------------------------------

async def compute_and_store_hash(
	document_id: str,
	file_bytes: bytes,
	text_content: str | None,
	tenant_id: str,
	session: AsyncSession,
) -> DocumentHash:
	"""Create or update the DocumentHash record for *document_id*."""
	fh = compute_file_hash(file_bytes)
	ch = compute_text_hash(text_content) if text_content else None

	stmt = select(DocumentHash).where(DocumentHash.document_id == document_id)
	result = await session.execute(stmt)
	record = result.scalar_one_or_none()

	if record is None:
		record = DocumentHash(
			id=uuid7str(),
			document_id=document_id,
			file_hash=fh,
			content_hash=ch,
			tenant_id=tenant_id,
		)
		session.add(record)
	else:
		record.file_hash = fh
		record.content_hash = ch
		record.updated_at = datetime.utcnow()

	await session.commit()
	await session.refresh(record)
	return record


async def find_duplicates(
	document_id: str,
	tenant_id: str,
	session: AsyncSession,
) -> list[dict]:
	"""
	Return documents (same tenant, different id) that share the file_hash
	or content_hash of *document_id*.

	Each entry: {document_id, title, created_at, match_type: "exact"|"content"}
	"""
	# Fetch the hashes for the target document
	stmt = select(DocumentHash).where(DocumentHash.document_id == document_id)
	result = await session.execute(stmt)
	own = result.scalar_one_or_none()

	if own is None:
		log.debug("find_duplicates: no hash record for document %s", document_id)
		return []

	candidates: list[dict] = []
	seen: set[str] = set()

	# --- exact file match ---
	if own.file_hash:
		rows = await session.execute(
			text(
				"SELECT dh.document_id, n.title, n.created_at "
				"FROM document_hashes dh "
				"JOIN nodes n ON n.id::text = dh.document_id "
				"WHERE dh.file_hash = :fh "
				"  AND dh.tenant_id = :tid "
				"  AND dh.document_id != :did"
			),
			{"fh": own.file_hash, "tid": tenant_id, "did": document_id},
		)
		for r in rows.fetchall():
			did = str(r.document_id)
			if did not in seen:
				seen.add(did)
				candidates.append(
					{
						"document_id": did,
						"title": r.title,
						"created_at": r.created_at,
						"match_type": "exact",
					}
				)

	# --- content (text) match ---
	if own.content_hash:
		rows = await session.execute(
			text(
				"SELECT dh.document_id, n.title, n.created_at "
				"FROM document_hashes dh "
				"JOIN nodes n ON n.id::text = dh.document_id "
				"WHERE dh.content_hash = :ch "
				"  AND dh.tenant_id = :tid "
				"  AND dh.document_id != :did"
			),
			{"ch": own.content_hash, "tid": tenant_id, "did": document_id},
		)
		for r in rows.fetchall():
			did = str(r.document_id)
			if did not in seen:
				seen.add(did)
				candidates.append(
					{
						"document_id": did,
						"title": r.title,
						"created_at": r.created_at,
						"match_type": "content",
					}
				)

	return candidates


async def check_file_hash_duplicate(
	file_hash: str,
	tenant_id: str,
	session: AsyncSession,
) -> list[dict]:
	"""
	Pre-upload check: given a file_hash, return any existing documents with
	the same hash (same tenant).

	Each entry: {document_id, title, created_at, match_type: "exact"}
	"""
	rows = await session.execute(
		text(
			"SELECT dh.document_id, n.title, n.created_at "
			"FROM document_hashes dh "
			"JOIN nodes n ON n.id::text = dh.document_id "
			"WHERE dh.file_hash = :fh AND dh.tenant_id = :tid"
		),
		{"fh": file_hash, "tid": tenant_id},
	)
	return [
		{
			"document_id": str(r.document_id),
			"title": r.title,
			"created_at": r.created_at,
			"match_type": "exact",
		}
		for r in rows.fetchall()
	]
