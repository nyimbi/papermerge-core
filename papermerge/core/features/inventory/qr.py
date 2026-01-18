# (c) Copyright Datacraft, 2026
"""
QR Code and Data Matrix generation for physical document tracking.
"""
import io
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers import (
	RoundedModuleDrawer,
	SquareModuleDrawer,
)
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import LETTER, A4
from reportlab.lib.units import mm, inch
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode import qr as reportlab_qr
from reportlab.graphics import renderPDF
from reportlab.graphics.shapes import Drawing

try:
	from pylibdmtx.pylibdmtx import encode as dmtx_encode
	DMTX_AVAILABLE = True
except ImportError:
	DMTX_AVAILABLE = False


@dataclass
class LabelData:
	"""Data to encode in a label."""
	document_id: str
	batch_id: str | None = None
	location_code: str | None = None
	box_label: str | None = None
	folder_label: str | None = None
	sequence_number: int | None = None
	created_at: str | None = None
	tenant_slug: str | None = None

	def to_compact_string(self) -> str:
		"""Create compact string for encoding."""
		parts = [f"D:{self.document_id}"]
		if self.batch_id:
			parts.append(f"B:{self.batch_id}")
		if self.location_code:
			parts.append(f"L:{self.location_code}")
		if self.sequence_number is not None:
			parts.append(f"S:{self.sequence_number}")
		return "|".join(parts)

	def to_json(self) -> str:
		"""Create JSON string for encoding."""
		data = {k: v for k, v in {
			"doc": self.document_id,
			"batch": self.batch_id,
			"loc": self.location_code,
			"box": self.box_label,
			"folder": self.folder_label,
			"seq": self.sequence_number,
			"ts": self.created_at,
		}.items() if v is not None}
		return json.dumps(data, separators=(',', ':'))

	def to_url(self, base_url: str) -> str:
		"""Create URL for document access."""
		url = f"{base_url.rstrip('/')}/documents/{self.document_id}"
		if self.tenant_slug:
			url = f"{base_url.rstrip('/')}/{self.tenant_slug}/documents/{self.document_id}"
		return url


class QRCodeGenerator:
	"""Generate QR codes for document tracking."""

	def __init__(
		self,
		error_correction: Literal['L', 'M', 'Q', 'H'] = 'M',
		box_size: int = 10,
		border: int = 4,
		style: Literal['square', 'rounded'] = 'square',
	):
		self.error_correction = {
			'L': qrcode.constants.ERROR_CORRECT_L,
			'M': qrcode.constants.ERROR_CORRECT_M,
			'Q': qrcode.constants.ERROR_CORRECT_Q,
			'H': qrcode.constants.ERROR_CORRECT_H,
		}[error_correction]
		self.box_size = box_size
		self.border = border
		self.style = style

	def generate(
		self,
		data: str | LabelData,
		size: tuple[int, int] | None = None,
		format: Literal['compact', 'json', 'url'] = 'compact',
		base_url: str | None = None,
	) -> Image.Image:
		"""Generate QR code image."""
		if isinstance(data, LabelData):
			if format == 'url' and base_url:
				encoded_data = data.to_url(base_url)
			elif format == 'json':
				encoded_data = data.to_json()
			else:
				encoded_data = data.to_compact_string()
		else:
			encoded_data = data

		qr = qrcode.QRCode(
			version=None,
			error_correction=self.error_correction,
			box_size=self.box_size,
			border=self.border,
		)
		qr.add_data(encoded_data)
		qr.make(fit=True)

		if self.style == 'rounded':
			img = qr.make_image(
				image_factory=StyledPilImage,
				module_drawer=RoundedModuleDrawer(),
			)
		else:
			img = qr.make_image(fill_color="black", back_color="white")

		if size:
			img = img.resize(size, Image.Resampling.LANCZOS)

		return img.convert('RGB')

	def generate_with_label(
		self,
		data: LabelData,
		label_text: str | None = None,
		size: tuple[int, int] = (200, 240),
		font_size: int = 12,
	) -> Image.Image:
		"""Generate QR code with text label below."""
		qr_size = (size[0], size[0])
		qr_img = self.generate(data, size=qr_size)

		# Create combined image
		combined = Image.new('RGB', size, 'white')
		combined.paste(qr_img, (0, 0))

		# Add label
		draw = ImageDraw.Draw(combined)
		label = label_text or data.to_compact_string()

		try:
			font = ImageFont.truetype("DejaVuSans.ttf", font_size)
		except OSError:
			font = ImageFont.load_default()

		# Calculate text position
		bbox = draw.textbbox((0, 0), label, font=font)
		text_width = bbox[2] - bbox[0]
		text_x = (size[0] - text_width) // 2
		text_y = size[0] + 5

		draw.text((text_x, text_y), label, fill='black', font=font)

		return combined

	def save(
		self,
		data: str | LabelData,
		path: Path | str,
		format: str = 'PNG',
		**kwargs,
	) -> None:
		"""Save QR code to file."""
		img = self.generate(data, **kwargs)
		img.save(str(path), format=format)


class DataMatrixGenerator:
	"""Generate Data Matrix codes for high-density encoding."""

	def __init__(self):
		if not DMTX_AVAILABLE:
			raise RuntimeError(
				"pylibdmtx is not installed. "
				"Install with: pip install pylibdmtx"
			)

	def generate(
		self,
		data: str | LabelData,
		size: tuple[int, int] | None = None,
	) -> Image.Image:
		"""Generate Data Matrix image."""
		if isinstance(data, LabelData):
			encoded_data = data.to_compact_string()
		else:
			encoded_data = data

		encoded = dmtx_encode(encoded_data.encode('utf-8'))
		img = Image.frombytes('RGB', (encoded.width, encoded.height), encoded.pixels)

		if size:
			img = img.resize(size, Image.Resampling.LANCZOS)

		return img

	def save(
		self,
		data: str | LabelData,
		path: Path | str,
		format: str = 'PNG',
		**kwargs,
	) -> None:
		"""Save Data Matrix to file."""
		img = self.generate(data, **kwargs)
		img.save(str(path), format=format)


class LabelSheetGenerator:
	"""Generate printable sheets of labels."""

	def __init__(
		self,
		page_size: tuple[float, float] = LETTER,
		margin: float = 0.5 * inch,
		label_width: float = 2 * inch,
		label_height: float = 1 * inch,
		h_spacing: float = 0.125 * inch,
		v_spacing: float = 0,
	):
		self.page_size = page_size
		self.margin = margin
		self.label_width = label_width
		self.label_height = label_height
		self.h_spacing = h_spacing
		self.v_spacing = v_spacing

		# Calculate grid
		usable_width = page_size[0] - 2 * margin
		usable_height = page_size[1] - 2 * margin

		self.cols = int((usable_width + h_spacing) / (label_width + h_spacing))
		self.rows = int((usable_height + v_spacing) / (label_height + v_spacing))
		self.labels_per_page = self.cols * self.rows

	def generate_pdf(
		self,
		labels: list[LabelData],
		output_path: Path | str,
		include_text: bool = True,
	) -> None:
		"""Generate PDF with label sheet."""
		c = canvas.Canvas(str(output_path), pagesize=self.page_size)
		qr_gen = QRCodeGenerator(box_size=4, border=2)

		for page_start in range(0, len(labels), self.labels_per_page):
			page_labels = labels[page_start:page_start + self.labels_per_page]

			for idx, label_data in enumerate(page_labels):
				row = idx // self.cols
				col = idx % self.cols

				x = self.margin + col * (self.label_width + self.h_spacing)
				# PDF coordinates are from bottom
				y = self.page_size[1] - self.margin - (row + 1) * (self.label_height + self.v_spacing)

				# Generate QR
				qr_img = qr_gen.generate(label_data)
				qr_size = min(self.label_width, self.label_height) * 0.7

				# Save temporary PNG and draw
				img_buffer = io.BytesIO()
				qr_img.save(img_buffer, format='PNG')
				img_buffer.seek(0)

				from reportlab.lib.utils import ImageReader
				c.drawImage(
					ImageReader(img_buffer),
					x + 5,
					y + (self.label_height - qr_size) / 2,
					width=qr_size,
					height=qr_size,
				)

				if include_text:
					text_x = x + qr_size + 10
					text_y = y + self.label_height - 15

					c.setFont("Helvetica", 8)

					lines = []
					if label_data.box_label:
						lines.append(f"Box: {label_data.box_label}")
					if label_data.folder_label:
						lines.append(f"Folder: {label_data.folder_label}")
					if label_data.sequence_number is not None:
						lines.append(f"Doc #{label_data.sequence_number}")
					lines.append(f"ID: {label_data.document_id[:8]}...")

					for i, line in enumerate(lines[:4]):
						c.drawString(text_x, text_y - i * 10, line)

			if page_start + self.labels_per_page < len(labels):
				c.showPage()

		c.save()

	def generate_avery_5160(
		self,
		labels: list[LabelData],
		output_path: Path | str,
	) -> None:
		"""Generate PDF for Avery 5160 labels (30 per sheet)."""
		self.page_size = LETTER
		self.margin = 0.21975 * inch
		self.label_width = 2.625 * inch
		self.label_height = 1 * inch
		self.h_spacing = 0.125 * inch
		self.v_spacing = 0
		self.cols = 3
		self.rows = 10
		self.labels_per_page = 30

		self.generate_pdf(labels, output_path)
