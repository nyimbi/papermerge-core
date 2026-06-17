# (c) Copyright Datacraft, 2026
"""QR code and document label generation service.

Dependencies:
  qrcode[pil]  — already in pyproject.toml
  pymupdf      — fitz; used elsewhere in the project for PDF ops
"""
import io
import logging
from datetime import datetime

_log = logging.getLogger(__name__)


def generate_qr_code(data: str, size: int = 200) -> bytes:
	"""Return a PNG-encoded QR code for *data*.

	Args:
		data: The payload to encode (typically a document URL).
		size: Desired image dimension in pixels (square). Minimum 21 px.

	Returns:
		Raw PNG bytes.
	"""
	import qrcode

	box_size = max(1, size // 21)
	qr = qrcode.QRCode(
		version=1,
		error_correction=qrcode.constants.ERROR_CORRECT_M,
		box_size=box_size,
		border=2,
	)
	qr.add_data(data)
	qr.make(fit=True)

	img = qr.make_image(fill_color="black", back_color="white")

	buf = io.BytesIO()
	img.save(buf, format="PNG")
	return buf.getvalue()


def generate_document_label_pdf(
	document_id: str,
	title: str,
	created_at: str,
	base_url: str,
) -> bytes:
	"""Return an A6-sized PDF label as bytes.

	Layout (left-to-right):
	  ┌───────────────┬──────────────────────────────┐
	  │  QR code      │  Title (truncated, 40 chars) │
	  │  120 × 120 px │  ID                          │
	  │               │  Created at                  │
	  └───────────────┴──────────────────────────────┘

	Args:
		document_id: UUID string for the document.
		title:       Human-readable document title.
		created_at:  ISO-8601 date/time string.
		base_url:    Application root URL used to build the QR payload.

	Returns:
		PDF bytes (single A6 page).
	"""
	try:
		import fitz  # PyMuPDF
	except ImportError as exc:
		raise RuntimeError(
			"PyMuPDF (fitz) is required for label generation. "
			"Install it with: pip install pymupdf"
		) from exc

	# A6 in points: 105 × 148 mm  →  297.6 × 419.5 pt
	A6_W, A6_H = 297.6, 419.5

	doc = fitz.open()
	page = doc.new_page(width=A6_W, height=A6_H)

	# ── QR code ──────────────────────────────────────────────────────────────
	qr_url = f"{base_url.rstrip('/')}/document/{document_id}"
	qr_png = generate_qr_code(qr_url, size=120)

	qr_margin = 12.0
	qr_size = 120.0
	qr_rect = fitz.Rect(qr_margin, qr_margin, qr_margin + qr_size, qr_margin + qr_size)
	page.insert_image(qr_rect, stream=qr_png)

	# ── Text block ───────────────────────────────────────────────────────────
	text_x = qr_margin + qr_size + 10
	text_y_start = qr_margin + 8

	title_trunc = title[:40] + ("…" if len(title) > 40 else "")
	id_trunc = document_id[:24] + ("…" if len(document_id) > 24 else "")

	# Title — bold-ish via a slightly larger font
	page.insert_text(
		(text_x, text_y_start + 14),
		title_trunc,
		fontsize=10,
		fontname="helv",
		color=(0, 0, 0),
	)

	# Document ID
	page.insert_text(
		(text_x, text_y_start + 32),
		f"ID: {id_trunc}",
		fontsize=7,
		fontname="cour",
		color=(0.3, 0.3, 0.3),
	)

	# Created at
	page.insert_text(
		(text_x, text_y_start + 46),
		f"Created: {created_at}",
		fontsize=7,
		fontname="helv",
		color=(0.3, 0.3, 0.3),
	)

	# ── URL (small, below QR) ────────────────────────────────────────────────
	page.insert_text(
		(qr_margin, qr_margin + qr_size + 14),
		qr_url[:55],
		fontsize=6,
		fontname="helv",
		color=(0.4, 0.4, 0.4),
	)

	buf = io.BytesIO()
	doc.save(buf)
	doc.close()
	return buf.getvalue()


def generate_batch_labels_pdf(
	labels: list[dict],
	base_url: str,
) -> bytes:
	"""Combine multiple A6 labels into an A4 PDF (2 per page, portrait).

	Args:
		labels:   List of dicts with keys: document_id, title, created_at.
		base_url: Application root URL.

	Returns:
		PDF bytes (A4 pages, 2 labels per page).
	"""
	try:
		import fitz
	except ImportError as exc:
		raise RuntimeError("PyMuPDF (fitz) is required.") from exc

	# A4 portrait in points: 595 × 842 pt
	A4_W, A4_H = 595.0, 842.0

	out_doc = fitz.open()

	for i in range(0, len(labels), 2):
		page = out_doc.new_page(width=A4_W, height=A4_H)

		for slot, label in enumerate(labels[i : i + 2]):
			label_pdf_bytes = generate_document_label_pdf(
				document_id=label["document_id"],
				title=label.get("title", "Untitled"),
				created_at=label.get("created_at", ""),
				base_url=base_url,
			)

			src = fitz.open("pdf", label_pdf_bytes)
			# slot 0 → top half, slot 1 → bottom half
			y_offset = slot * (A4_H / 2)
			target_rect = fitz.Rect(0, y_offset, A4_W, y_offset + A4_H / 2)
			page.show_pdf_page(target_rect, src, 0)
			src.close()

	buf = io.BytesIO()
	out_doc.save(buf)
	out_doc.close()
	return buf.getvalue()
