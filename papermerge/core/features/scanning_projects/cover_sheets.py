# (c) Copyright Datacraft, 2026
"""Cover sheet and separator sheet PDF generation for scanning batches.

Dependencies:
    qrcode[pil]  — already in pyproject.toml
    pymupdf      — fitz; already used in qr/service.py
"""
import io
import logging
from datetime import date

_log = logging.getLogger(__name__)

# A4 dimensions in PDF points (1 pt = 1/72 inch)
_A4_W = 595.0
_A4_H = 842.0

# A5 dimensions (half-A4 portrait)
_A5_W = 420.0
_A5_H = 595.0


def _qr_png(data: str, size: int) -> bytes:
	"""Generate a square QR code PNG at *size* pixels."""
	import qrcode

	box_size = max(1, size // 21)
	qr = qrcode.QRCode(
		version=None,
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


def generate_cover_sheet_pdf(
	project_id: str,
	project_name: str,
	batch_number: int,
) -> bytes:
	"""Generate an A4 PDF cover sheet for a scanning batch.

	Contents:
	- System header: "dArchiva Document Management System"
	- Large QR code (200x200px) centered encoding "PROJ-{project_id}-BATCH-{batch_number}"
	- "Scan Code: PROJ-{project_id}-BATCH-{batch_number}" below QR
	- Project name (large, bold)
	- Batch number: "Batch #{batch_number}"
	- Today's date
	- Instructions (small): "Place this sheet at the START of your document batch"
	- Dashed border around the page

	Returns:
	    PDF bytes (single A4 page).
	"""
	try:
		import fitz
	except ImportError as exc:
		raise RuntimeError(
			"PyMuPDF (fitz) is required for cover sheet generation. "
			"Install it with: pip install pymupdf"
		) from exc

	scan_code = f"PROJ-{project_id}-BATCH-{batch_number}"
	qr_size = 200

	qr_png = _qr_png(scan_code, qr_size)

	doc = fitz.open()
	page = doc.new_page(width=_A4_W, height=_A4_H)

	# ── Dashed border ─────────────────────────────────────────────────────────
	margin = 18.0
	border_rect = fitz.Rect(margin, margin, _A4_W - margin, _A4_H - margin)
	# Draw as a thin rounded rect with gray color; fitz doesn't natively do
	# dashes, so we draw a solid thin border and add tick marks to simulate it.
	page.draw_rect(border_rect, color=(0.5, 0.5, 0.5), width=1.2, dashes="[4 4] 0")

	# ── Header ────────────────────────────────────────────────────────────────
	header_y = 52.0
	page.insert_text(
		(_A4_W / 2, header_y),
		"dArchiva Document Management System",
		fontsize=13,
		fontname="helv",
		color=(0.15, 0.15, 0.15),
		align=fitz.TEXT_ALIGN_CENTER,
	)

	# Thin separator line under header
	line_y = header_y + 12
	page.draw_line(
		fitz.Point(margin + 10, line_y),
		fitz.Point(_A4_W - margin - 10, line_y),
		color=(0.7, 0.7, 0.7),
		width=0.8,
	)

	# ── QR Code (centered) ────────────────────────────────────────────────────
	qr_top = line_y + 28
	qr_left = (_A4_W - qr_size) / 2
	qr_rect = fitz.Rect(qr_left, qr_top, qr_left + qr_size, qr_top + qr_size)
	page.insert_image(qr_rect, stream=qr_png)

	# ── Scan code label below QR ──────────────────────────────────────────────
	code_y = qr_top + qr_size + 18
	page.insert_text(
		(_A4_W / 2, code_y),
		f"Scan Code: {scan_code}",
		fontsize=9,
		fontname="cour",
		color=(0.25, 0.25, 0.25),
		align=fitz.TEXT_ALIGN_CENTER,
	)

	# ── Project name ──────────────────────────────────────────────────────────
	proj_y = code_y + 42
	# Truncate long project names
	proj_display = project_name if len(project_name) <= 52 else project_name[:49] + "..."
	page.insert_text(
		(_A4_W / 2, proj_y),
		proj_display,
		fontsize=20,
		fontname="helvB",
		color=(0.05, 0.05, 0.05),
		align=fitz.TEXT_ALIGN_CENTER,
	)

	# ── Batch number ──────────────────────────────────────────────────────────
	batch_y = proj_y + 34
	page.insert_text(
		(_A4_W / 2, batch_y),
		f"Batch #{batch_number}",
		fontsize=16,
		fontname="helv",
		color=(0.2, 0.2, 0.7),
		align=fitz.TEXT_ALIGN_CENTER,
	)

	# ── Date ──────────────────────────────────────────────────────────────────
	date_y = batch_y + 28
	today = date.today().strftime("%d %B %Y")
	page.insert_text(
		(_A4_W / 2, date_y),
		today,
		fontsize=11,
		fontname="helv",
		color=(0.4, 0.4, 0.4),
		align=fitz.TEXT_ALIGN_CENTER,
	)

	# ── Instructions (bottom) ─────────────────────────────────────────────────
	instr_y = _A4_H - margin - 22
	page.insert_text(
		(_A4_W / 2, instr_y),
		"Place this sheet at the START of your document batch",
		fontsize=9,
		fontname="helv",
		color=(0.5, 0.5, 0.5),
		align=fitz.TEXT_ALIGN_CENTER,
	)

	buf = io.BytesIO()
	doc.save(buf)
	doc.close()
	return buf.getvalue()


def generate_separator_sheet_pdf(
	project_id: str,
	project_name: str,
) -> bytes:
	"""Generate an A5 separator sheet for a scanning project.

	Contents:
	- QR code (150x150) encoding "PROJ-{project_id}-SEP"
	- "SEPARATOR" label in large red text
	- Project name
	- "Place between documents to trigger auto-split"

	Returns:
	    PDF bytes (single A5 page).
	"""
	try:
		import fitz
	except ImportError as exc:
		raise RuntimeError("PyMuPDF (fitz) is required for separator sheet generation.") from exc

	sep_code = f"PROJ-{project_id}-SEP"
	qr_size = 150

	qr_png = _qr_png(sep_code, qr_size)

	doc = fitz.open()
	page = doc.new_page(width=_A5_W, height=_A5_H)

	margin = 16.0

	# ── Dashed border ─────────────────────────────────────────────────────────
	border_rect = fitz.Rect(margin, margin, _A5_W - margin, _A5_H - margin)
	page.draw_rect(border_rect, color=(0.7, 0.2, 0.2), width=1.5, dashes="[6 4] 0")

	# ── "SEPARATOR" label ─────────────────────────────────────────────────────
	sep_label_y = 52.0
	page.insert_text(
		(_A5_W / 2, sep_label_y),
		"SEPARATOR",
		fontsize=26,
		fontname="helvB",
		color=(0.75, 0.1, 0.1),
		align=fitz.TEXT_ALIGN_CENTER,
	)

	# ── QR Code (centered) ────────────────────────────────────────────────────
	qr_top = sep_label_y + 20
	qr_left = (_A5_W - qr_size) / 2
	qr_rect = fitz.Rect(qr_left, qr_top, qr_left + qr_size, qr_top + qr_size)
	page.insert_image(qr_rect, stream=qr_png)

	# ── Scan code below QR ───────────────────────────────────────────────────
	code_y = qr_top + qr_size + 14
	page.insert_text(
		(_A5_W / 2, code_y),
		sep_code,
		fontsize=8,
		fontname="cour",
		color=(0.3, 0.3, 0.3),
		align=fitz.TEXT_ALIGN_CENTER,
	)

	# ── Project name ──────────────────────────────────────────────────────────
	proj_y = code_y + 28
	proj_display = project_name if len(project_name) <= 40 else project_name[:37] + "..."
	page.insert_text(
		(_A5_W / 2, proj_y),
		proj_display,
		fontsize=13,
		fontname="helvB",
		color=(0.1, 0.1, 0.1),
		align=fitz.TEXT_ALIGN_CENTER,
	)

	# ── Instructions ──────────────────────────────────────────────────────────
	instr_y = _A5_H - margin - 18
	page.insert_text(
		(_A5_W / 2, instr_y),
		"Place between documents to trigger auto-split",
		fontsize=8,
		fontname="helv",
		color=(0.5, 0.5, 0.5),
		align=fitz.TEXT_ALIGN_CENTER,
	)

	buf = io.BytesIO()
	doc.save(buf)
	doc.close()
	return buf.getvalue()


def generate_batch_cover_sheets(
	project_id: str,
	project_name: str,
	batch_count: int,
) -> bytes:
	"""Generate a multi-page PDF with *batch_count* cover sheets (one per page).

	Batch numbers are sequential starting from 1.

	Returns:
	    PDF bytes (batch_count A4 pages).
	"""
	try:
		import fitz
	except ImportError as exc:
		raise RuntimeError("PyMuPDF (fitz) is required.") from exc

	if batch_count < 1:
		raise ValueError("batch_count must be >= 1")
	if batch_count > 50:
		raise ValueError("batch_count must be <= 50")

	out_doc = fitz.open()

	for batch_number in range(1, batch_count + 1):
		sheet_bytes = generate_cover_sheet_pdf(project_id, project_name, batch_number)
		src = fitz.open("pdf", sheet_bytes)
		out_doc.insert_pdf(src)
		src.close()

	buf = io.BytesIO()
	out_doc.save(buf)
	out_doc.close()
	return buf.getvalue()
