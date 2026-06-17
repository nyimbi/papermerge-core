"""
Signature stamping service.

Decodes a base64 PNG signature and burns it onto the specified page of a
document using PyMuPDF, producing a new document version.
"""
import base64
import io
import logging
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


async def apply_signature_to_document(
	doc_id: str,
	page_num: int,
	sig_data_b64: str,
	x: float,
	y: float,
	w: float,
	h: float,
	session,  # AsyncSession — passed through but storage is file-based
) -> str:
	"""
	Stamp a base64-encoded PNG signature onto a document page.

	Coordinates (x, y, w, h) are normalised fractions of page dimensions
	(0.0–1.0).  Returns the ID of the newly created signed document.

	The function:
	1. Decodes the base64 PNG.
	2. Locates the latest document version file on disk.
	3. Opens it with PyMuPDF, computes absolute rect, inserts the image.
	4. Saves the result under a new ID.
	5. Returns new_document_id.

	Storage layout assumed:
	  <MEDIA_ROOT>/documents/<doc_id>/versions/<ver>/pages/  (PDF per version)
	  or a single PDF at <MEDIA_ROOT>/documents/<doc_id>/<doc_id>.pdf

	We try the flat layout first, then the versioned layout.
	"""
	try:
		import fitz  # PyMuPDF
	except ImportError as exc:
		raise RuntimeError(
			"PyMuPDF (fitz) is required for signature stamping. "
			"Install it with: pip install pymupdf"
		) from exc

	# --- locate source PDF ---------------------------------------------------
	source_path = _find_document_pdf(doc_id)
	if source_path is None:
		raise FileNotFoundError(f"No PDF found for document {doc_id}")

	# --- decode signature image ----------------------------------------------
	sig_bytes = base64.b64decode(sig_data_b64)

	# --- open and stamp ------------------------------------------------------
	pdf_doc = fitz.open(str(source_path))

	page_index = max(0, page_num - 1)  # 1-based → 0-based
	if page_index >= len(pdf_doc):
		page_index = len(pdf_doc) - 1

	page = pdf_doc[page_index]
	pw, ph = page.rect.width, page.rect.height

	# Convert normalised coords to absolute points
	abs_x = x * pw
	abs_y = y * ph
	abs_w = w * pw
	abs_h = h * ph
	rect = fitz.Rect(abs_x, abs_y, abs_x + abs_w, abs_y + abs_h)

	page.insert_image(rect, stream=sig_bytes)

	# --- save to new path ---------------------------------------------------
	new_document_id = str(uuid.uuid4())
	dest_path = _signed_document_path(doc_id, new_document_id)
	dest_path.parent.mkdir(parents=True, exist_ok=True)
	pdf_doc.save(str(dest_path))
	pdf_doc.close()

	logger.info(
		"Signature stamped: doc=%s page=%d -> new_doc=%s path=%s",
		doc_id, page_num, new_document_id, dest_path,
	)
	return new_document_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_document_pdf(doc_id: str) -> Optional[Path]:
	"""Return the path to the most recent PDF for doc_id, or None."""
	from papermerge.core.config import get_settings

	try:
		settings = get_settings()
		media_root = Path(settings.media_root)
	except Exception:
		media_root = Path("/var/media")

	# Flat layout: <media_root>/documents/<doc_id>/<doc_id>.pdf
	flat = media_root / "documents" / doc_id / f"{doc_id}.pdf"
	if flat.exists():
		return flat

	# Versioned layout: pick the highest-numbered version dir
	versioned_base = media_root / "documents" / doc_id / "versions"
	if versioned_base.is_dir():
		version_dirs = sorted(versioned_base.iterdir(), key=lambda p: p.name)
		for ver_dir in reversed(version_dirs):
			candidate = ver_dir / f"{doc_id}.pdf"
			if candidate.exists():
				return candidate
			# Some layouts put it at ver_dir/<ver>.pdf or ver_dir/document.pdf
			for pdf in ver_dir.glob("*.pdf"):
				return pdf

	logger.warning("No PDF found for document %s under %s", doc_id, media_root)
	return None


def _signed_document_path(original_doc_id: str, new_doc_id: str) -> Path:
	"""Return the destination path for the signed document PDF."""
	from papermerge.core.config import get_settings

	try:
		settings = get_settings()
		media_root = Path(settings.media_root)
	except Exception:
		media_root = Path("/var/media")

	return media_root / "documents" / original_doc_id / "signed" / f"{new_doc_id}.pdf"
