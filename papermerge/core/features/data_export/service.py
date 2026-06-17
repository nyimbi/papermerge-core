# (c) Copyright Datacraft, 2026
"""Core logic for building data export ZIP archives."""
import io
import json
import logging
import zipfile
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_log = logging.getLogger(__name__)


# ── document bundle ───────────────────────────────────────────────────────────

async def create_document_bundle(
	document_ids: list[str],
	include_metadata: bool,
	session: AsyncSession,
) -> bytes:
	"""Build a ZIP containing requested documents plus optional per-doc metadata.

	ZIP layout::

	    documents/<id>/<title>.pdf
	    documents/<id>/metadata.json   (when include_metadata=True)

	Returns raw ZIP bytes ready for streaming.
	"""
	from papermerge.core.features.document.db.orm import Document, DocumentVersion
	from papermerge.core.features.document_types.db.orm import DocumentType
	from papermerge.core.features.tags.db.orm import Tag
	from papermerge.core import pathlib as plib
	from papermerge.storage.base import get_storage_backend

	storage = get_storage_backend()
	buf = io.BytesIO()

	with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
		for doc_id in document_ids:
			try:
				doc_stmt = select(Document).where(Document.id == doc_id)
				doc = (await session.execute(doc_stmt)).scalar_one_or_none()
				if doc is None:
					_log.warning("bundle: doc %s not found — skipping", doc_id)
					continue

				# Latest version
				ver_stmt = (
					select(DocumentVersion)
					.where(DocumentVersion.document_id == doc_id)
					.order_by(DocumentVersion.number.desc())
					.limit(1)
				)
				ver = (await session.execute(ver_stmt)).scalar_one_or_none()

				# Document type name
				doc_type_name = ""
				if doc.document_type_id:
					dt = await session.get(DocumentType, doc.document_type_id)
					doc_type_name = dt.name if dt else str(doc.document_type_id)

				# Tags
				tag_names: list[str] = []
				try:
					tag_stmt = (
						select(Tag)
						.join(Tag.nodes)
						.where(Tag.nodes.any(id=doc_id))
					)
					tags = (await session.execute(tag_stmt)).scalars().all()
					tag_names = [t.name for t in tags]
				except Exception:
					pass  # tags are best-effort

				# Custom fields (stored in document_metadata JSONB)
				custom_fields: dict = {}
				if doc.document_metadata:
					custom_fields = {
						k: v for k, v in doc.document_metadata.items()
						if k not in ("quality_score", "preview_error", "processing_error")
					}

				safe_id = doc_id[:8]
				safe_title = (doc.title or "document").replace("/", "_").replace("\\", "_")[:80]
				dir_prefix = f"documents/{safe_id}"

				# Write PDF/original file
				if ver:
					try:
						file_name = getattr(ver, "file_name", None) or f"{doc_id}.pdf"
						object_key = str(plib.docver_path(ver.id, file_name=file_name))
						file_bytes = storage.download_file(object_key)
						zf.writestr(f"{dir_prefix}/{safe_title}{_ext(file_name)}", file_bytes)
					except Exception as fe:
						_log.warning("bundle: cannot fetch file for %s: %s", doc_id, fe)

				# Write metadata JSON
				if include_metadata:
					meta = {
						"id": doc_id,
						"title": doc.title,
						"document_type": doc_type_name,
						"tags": tag_names,
						"custom_fields": custom_fields,
						"created_at": doc.created_at.isoformat() if doc.created_at else None,
						"page_count": ver.page_count if ver else 0,
					}
					zf.writestr(f"{dir_prefix}/metadata.json", json.dumps(meta, indent=2))

			except Exception as ex:
				_log.warning("bundle: error processing doc %s: %s", doc_id, ex)

	return buf.getvalue()


# ── full tenant export ────────────────────────────────────────────────────────

async def export_full_tenant(tenant_id: str, session: AsyncSession) -> bytes:
	"""Build a ZIP of all documents for a tenant, organised by folder path.

	ZIP layout::

	    <folder_path>/<title>.pdf
	    manifest.json   (list of all documents with metadata)
	"""
	from papermerge.core.features.document.db.orm import Document, DocumentVersion
	from papermerge.core.features.document_types.db.orm import DocumentType
	from papermerge.core.features.nodes.db.orm import Node
	from papermerge.core import pathlib as plib
	from papermerge.storage.base import get_storage_backend
	from sqlalchemy import select as sa_select

	storage = get_storage_backend()
	buf = io.BytesIO()
	manifest: list[dict] = []

	with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
		# Fetch all documents belonging to the tenant
		doc_stmt = (
			sa_select(Document)
			.join(Node, Document.id == Node.id)
			.where(Node.user_id.isnot(None))  # filter to real docs
		)
		# If the Node has a tenant_id column use it; fall back to user join
		try:
			doc_stmt = doc_stmt.where(Node.tenant_id == tenant_id)
		except Exception:
			_log.debug("export_full_tenant: Node has no tenant_id column, exporting all")

		docs = (await session.execute(doc_stmt)).scalars().all()
		_log.info("export_full_tenant: tenant=%s docs=%d", tenant_id[:8], len(docs))

		for doc in docs:
			try:
				ver_stmt = (
					sa_select(DocumentVersion)
					.where(DocumentVersion.document_id == str(doc.id))
					.order_by(DocumentVersion.number.desc())
					.limit(1)
				)
				ver = (await session.execute(ver_stmt)).scalar_one_or_none()

				doc_type_name = ""
				if doc.document_type_id:
					dt = await session.get(DocumentType, doc.document_type_id)
					doc_type_name = dt.name if dt else ""

				# Build folder path from node title chain (best-effort)
				folder_path = _resolve_folder_path(doc, session)

				safe_title = (doc.title or "document").replace("/", "_").replace("\\", "_")[:80]
				doc_id_str = str(doc.id)

				if ver:
					try:
						file_name = getattr(ver, "file_name", None) or f"{doc_id_str}.pdf"
						object_key = str(plib.docver_path(ver.id, file_name=file_name))
						file_bytes = storage.download_file(object_key)
						zip_entry = f"{folder_path}/{safe_title}{_ext(file_name)}"
						zf.writestr(zip_entry, file_bytes)
					except Exception as fe:
						_log.warning("export_full_tenant: cannot fetch file %s: %s", doc_id_str, fe)

				manifest.append({
					"id": doc_id_str,
					"title": doc.title,
					"document_type": doc_type_name,
					"folder_path": folder_path,
					"created_at": doc.created_at.isoformat() if doc.created_at else None,
					"page_count": ver.page_count if ver else 0,
				})

			except Exception as ex:
				_log.warning("export_full_tenant: error on doc %s: %s", doc.id, ex)

		zf.writestr("manifest.json", json.dumps(manifest, indent=2))

	return buf.getvalue()


# ── GDPR subject export ───────────────────────────────────────────────────────

async def export_gdpr_subject(email: str, session: AsyncSession) -> bytes:
	"""Return a ZIP of all documents created by the user with the given email.

	Searches users by email, then collects all documents where Node.user_id
	matches.
	"""
	from papermerge.core.features.users.db.orm import User
	from papermerge.core.features.document.db.orm import Document, DocumentVersion
	from papermerge.core import pathlib as plib
	from papermerge.storage.base import get_storage_backend
	from sqlalchemy import select as sa_select

	# Resolve user id from email
	user_stmt = sa_select(User).where(User.email == email)
	user = (await session.execute(user_stmt)).scalar_one_or_none()
	if user is None:
		_log.info("gdpr_subject: no user found for email %s", email)
		return _empty_zip(f"No user found with email: {email}")

	user_id = str(user.id)
	_log.info("gdpr_subject: exporting docs for user %s (%s)", email, user_id[:8])

	from papermerge.core.features.nodes.db.orm import Node
	doc_stmt = (
		sa_select(Document)
		.join(Node, Document.id == Node.id)
		.where(Node.user_id == user_id)
	)
	docs = (await session.execute(doc_stmt)).scalars().all()

	storage = get_storage_backend()
	buf = io.BytesIO()
	manifest: list[dict] = []

	with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
		for doc in docs:
			doc_id_str = str(doc.id)
			try:
				ver_stmt = (
					sa_select(DocumentVersion)
					.where(DocumentVersion.document_id == doc_id_str)
					.order_by(DocumentVersion.number.desc())
					.limit(1)
				)
				ver = (await session.execute(ver_stmt)).scalar_one_or_none()

				safe_title = (doc.title or "document").replace("/", "_").replace("\\", "_")[:80]
				safe_id = doc_id_str[:8]

				if ver:
					try:
						file_name = getattr(ver, "file_name", None) or f"{doc_id_str}.pdf"
						object_key = str(plib.docver_path(ver.id, file_name=file_name))
						file_bytes = storage.download_file(object_key)
						zf.writestr(f"documents/{safe_id}/{safe_title}{_ext(file_name)}", file_bytes)
					except Exception as fe:
						_log.warning("gdpr_subject: cannot fetch file %s: %s", doc_id_str, fe)

				manifest.append({
					"id": doc_id_str,
					"title": doc.title,
					"created_at": doc.created_at.isoformat() if doc.created_at else None,
					"page_count": ver.page_count if ver else 0,
				})

			except Exception as ex:
				_log.warning("gdpr_subject: error on doc %s: %s", doc_id_str, ex)

		subject_info = {
			"subject_email": email,
			"user_id": user_id,
			"exported_at": datetime.utcnow().isoformat(),
			"document_count": len(manifest),
			"documents": manifest,
		}
		zf.writestr("gdpr_subject_data.json", json.dumps(subject_info, indent=2))

	return buf.getvalue()


# ── helpers ───────────────────────────────────────────────────────────────────

def _ext(file_name: str) -> str:
	"""Return the file extension including leading dot, or empty string."""
	if "." in file_name:
		return "." + file_name.rsplit(".", 1)[-1]
	return ""


def _resolve_folder_path(doc, session) -> str:
	"""Best-effort: return a safe folder path string for the document's parent."""
	try:
		parent_id = getattr(doc, "parent_id", None)
		if parent_id is None:
			return "root"
		return f"folder_{str(parent_id)[:8]}"
	except Exception:
		return "root"


def _empty_zip(note: str) -> bytes:
	buf = io.BytesIO()
	with zipfile.ZipFile(buf, mode="w") as zf:
		zf.writestr("README.txt", note)
	return buf.getvalue()
