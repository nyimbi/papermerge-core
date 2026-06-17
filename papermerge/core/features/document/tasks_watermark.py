# WIRING NEEDED: add "darchiva.documents.apply_watermark" to celery_app.py task routes
import asyncio
import logging
import uuid

from celery import shared_task

logger = logging.getLogger(__name__)


def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
	"""Convert #RRGGBB hex to (r, g, b) floats in [0, 1]."""
	h = hex_color.lstrip("#")
	if len(h) == 3:
		h = "".join(c * 2 for c in h)
	r = int(h[0:2], 16) / 255.0
	g = int(h[2:4], 16) / 255.0
	b = int(h[4:6], 16) / 255.0
	return r, g, b


def _parse_pages(pages_param, total: int) -> list[int]:
	"""Return 0-based page indices from 'all' or range string like '1-5, 8'."""
	if pages_param == "all" or pages_param is None:
		return list(range(total))
	if isinstance(pages_param, list):
		# Already a list of 1-based page numbers
		return [p - 1 for p in pages_param if 1 <= p <= total]
	# Parse a string like "1-5, 8, 10-12"
	indices: set[int] = set()
	for part in str(pages_param).split(","):
		part = part.strip()
		if "-" in part:
			lo, _, hi = part.partition("-")
			try:
				lo_i = int(lo.strip()) - 1
				hi_i = int(hi.strip()) - 1
				for i in range(max(0, lo_i), min(total - 1, hi_i) + 1):
					indices.add(i)
			except ValueError:
				pass
		else:
			try:
				i = int(part) - 1
				if 0 <= i < total:
					indices.add(i)
			except ValueError:
				pass
	return sorted(indices)


def _apply_watermark_to_pdf(
	src_path,
	dst_path,
	text: str,
	position: str,
	opacity: float,
	pages_param,
	font_size: int,
	color: str,
) -> None:
	"""
	Apply a text watermark to a PDF using PyMuPDF (fitz).

	Writes the watermarked PDF to dst_path.
	"""
	try:
		import fitz  # PyMuPDF
	except ImportError:
		raise RuntimeError(
			"PyMuPDF is not installed. "
			"Install it with: pip install pymupdf"
		)

	rgb = _hex_to_rgb(color)
	doc = fitz.open(str(src_path))
	target_indices = _parse_pages(pages_param, len(doc))

	for page_idx in target_indices:
		page = doc[page_idx]
		rect = page.rect
		w, h = rect.width, rect.height

		# Choose insertion point and rotation per position
		if position == "diagonal":
			# Center of page, 45-degree rotation
			point = fitz.Point(w / 2, h / 2)
			rotate = 45
			render_mode = 1  # stroke text for lighter visual
		elif position == "header":
			point = fitz.Point(w / 2, font_size * 1.5)
			rotate = 0
			render_mode = 0
		elif position == "footer":
			point = fitz.Point(w / 2, h - font_size * 0.5)
			rotate = 0
			render_mode = 0
		elif position == "corner":
			point = fitz.Point(w - font_size * 0.5, h - font_size * 0.5)
			rotate = 0
			render_mode = 0
		else:
			# Default: diagonal
			point = fitz.Point(w / 2, h / 2)
			rotate = 45
			render_mode = 0

		# Insert watermark text
		page.insert_text(
			point,
			text,
			fontsize=font_size,
			color=rgb,
			rotate=rotate,
			render_mode=render_mode,
			# PyMuPDF has no direct opacity param in insert_text;
			# we use an overlay annotation approach for transparency
		)

		# Apply opacity via a transparent rectangle overlay is not trivial.
		# Instead, blend the color with white at the given opacity level so
		# the watermark appears at the requested transparency (visually).
		# For true alpha we'd need to insert into a form XObject — skipping
		# that complexity; opacity blending is standard DMS practice.

	doc.save(str(dst_path), garbage=3, deflate=True)
	doc.close()


@shared_task(name="darchiva.documents.apply_watermark", bind=True)
def apply_watermark_task(
	self,
	document_id: str,
	watermark_params: dict,
	created_by_id: str,
	tenant_id: str,
) -> dict:
	"""
	Apply a text watermark to a document PDF and save as a new document.

	watermark_params keys:
	  text:     str                   Watermark text (e.g. "CONFIDENTIAL")
	  position: "diagonal"|"header"|"footer"|"corner"   default "diagonal"
	  opacity:  float 0.0-1.0         default 0.3
	  pages:    "all" | list[int]     default "all"
	  font_size: int                  default 36
	  color:    "#RRGGBB" hex string  default "#808080"

	Returns {document_id: str, version: str}
	"""
	logger.info(
		f"apply_watermark_task: doc={document_id} "
		f"text='{watermark_params.get('text', '')}' "
		f"position={watermark_params.get('position', 'diagonal')} "
		f"user={created_by_id[:8] if created_by_id else 'unknown'}"
	)

	text = watermark_params.get("text", "WATERMARK")
	position = watermark_params.get("position", "diagonal")
	opacity = float(watermark_params.get("opacity", 0.3))
	pages_param = watermark_params.get("pages", "all")
	font_size = int(watermark_params.get("font_size", 36))
	color = watermark_params.get("color", "#808080")

	# Clamp opacity
	opacity = max(0.05, min(1.0, opacity))
	# Blend color toward white based on inverse opacity so the text renders
	# lighter when lower opacity is requested (workaround for insert_text
	# not supporting native alpha).
	rgb = _hex_to_rgb(color)
	blended = tuple(c + (1.0 - c) * (1.0 - opacity) for c in rgb)
	effective_color = "#{:02x}{:02x}{:02x}".format(
		int(blended[0] * 255),
		int(blended[1] * 255),
		int(blended[2] * 255),
	)

	async def _run():
		from sqlalchemy import select as _select
		from papermerge.core.db.engine import get_async_session_maker
		from papermerge.core import orm as _orm
		from papermerge.core import schema
		from papermerge.core.features.document.db import api as doc_dbapi
		from papermerge.core.pathlib import abs_docver_path as _adp, docver_path as _dp
		from papermerge.core.config import get_settings
		import os

		config = get_settings()
		doc_uuid = uuid.UUID(document_id)
		user_uuid = uuid.UUID(created_by_id)

		async_session = get_async_session_maker()
		async with async_session() as session:
			# Load the latest version of the source document
			stmt = (
				_select(_orm.DocumentVersion)
				.where(_orm.DocumentVersion.document_id == doc_uuid)
				.order_by(_orm.DocumentVersion.number.desc())
				.limit(1)
			)
			result = await session.execute(stmt)
			src_ver = result.scalar_one_or_none()

			if src_ver is None:
				raise ValueError(f"Document {document_id} has no versions")

			# Try local file path first; fall back to downloading from storage
			src_path = src_ver.file_path
			tmp_src = None
			if not src_path.exists():
				# Download from storage backend to a temp file
				import tempfile
				from papermerge.storage.base import get_storage_backend
				from papermerge.core.pathlib import docver_path as _dver_path

				storage = get_storage_backend()
				object_key = str(_dver_path(src_ver.id, src_ver.file_name or "doc.pdf"))
				tmp_src_fd, tmp_src = tempfile.mkstemp(suffix=".pdf")
				os.close(tmp_src_fd)
				try:
					pdf_bytes = await storage.download_bytes(object_key=object_key)
					with open(tmp_src, "wb") as f:
						f.write(pdf_bytes)
					src_path = type(src_path)(tmp_src)  # pathlib.Path
				except Exception as dl_err:
					logger.error(f"Failed to download source PDF for watermarking: {dl_err}")
					raise

			# Build destination path for watermarked version
			new_ver_id = uuid.uuid4()
			src_file_name = src_ver.file_name or "document.pdf"
			stem, _, ext = src_file_name.rpartition(".")
			if not stem:
				stem, ext = src_file_name, "pdf"
			wm_file_name = f"{stem}_watermarked.{ext}"

			dst_path = _adp(new_ver_id, wm_file_name)
			os.makedirs(dst_path.parent, exist_ok=True)

			# Apply the watermark
			_apply_watermark_to_pdf(
				src_path=src_path,
				dst_path=dst_path,
				text=text,
				position=position,
				opacity=opacity,
				pages_param=pages_param,
				font_size=font_size,
				color=effective_color,
			)

			if tmp_src:
				try:
					os.unlink(tmp_src)
				except OSError:
					pass

			# Load parent folder
			doc_stmt = _select(_orm.Document).where(_orm.Document.id == doc_uuid)
			doc_result = await session.execute(doc_stmt)
			src_doc = doc_result.scalar_one_or_none()
			if src_doc is None:
				raise ValueError(f"Document ORM object not found for {document_id}")

			parent_id = src_doc.parent_id
			lang = (
				src_ver.lang
				or getattr(config, "default_lang", "eng")
			)

			wm_title = f"{src_doc.title} (watermarked)"
			wm_size = os.path.getsize(dst_path)
			new_doc_id = uuid.uuid4()

			new_doc_schema = schema.NewDocument(
				id=new_doc_id,
				title=wm_title,
				lang=lang,
				parent_id=parent_id,
				size=wm_size,
				page_count=src_ver.page_count or 0,
				ocr=False,
				file_name=wm_file_name,
				ctype="document",
				created_by=user_uuid,
				updated_by=user_uuid,
			)

			doc_obj = await doc_dbapi.create_document(
				session,
				new_doc_schema,
				mime_type="application/pdf",
				document_version_id=new_ver_id,
			)
			if isinstance(doc_obj, tuple):
				doc_obj, err = doc_obj
				if err:
					raise ValueError(f"create_document error: {err}")

			# Upload watermarked PDF to storage backend
			from papermerge.storage.base import get_storage_backend
			storage = get_storage_backend()
			object_key = str(_dp(new_ver_id, wm_file_name))
			try:
				with open(dst_path, "rb") as _f:
					wm_bytes = _f.read()
				await storage.upload_bytes(
					data=wm_bytes,
					object_key=object_key,
					content_type="application/pdf",
				)
			except Exception as upload_err:
				logger.warning(
					f"Storage upload of watermarked PDF failed (non-fatal for local): {upload_err}"
				)

			return {"document_id": str(doc_obj.id), "version": str(new_ver_id)}

	result = asyncio.run(_run())
	logger.info(
		f"apply_watermark_task: completed -> new doc {result['document_id']}"
	)
	return result
