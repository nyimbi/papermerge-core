# (c) Copyright Datacraft, 2026
"""Service for generating physical manifest PDF barcode sheets."""
import io
from datetime import datetime
from uuid import UUID

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode import code128
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db.orm import PhysicalManifest


class ManifestService:
    """Service to handle physical manifest operations."""

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session

    async def create_manifest(
        self,
        tenant_id: UUID,
        barcode: str,
        description: str | None = None,
        location_path: str | None = None,
        responsible_person: str | None = None,
    ) -> PhysicalManifest:
        """Create a new physical manifest."""
        manifest = PhysicalManifest(
            tenant_id=tenant_id,
            barcode=barcode,
            description=description,
            location_path=location_path,
            responsible_person=responsible_person,
        )
        self.db_session.add(manifest)
        await self.db_session.commit()
        await self.db_session.refresh(manifest)
        return manifest

    async def get_manifest(self, manifest_id: UUID, tenant_id: UUID) -> PhysicalManifest | None:
        """Get a manifest by ID."""
        result = await self.db_session.execute(
            select(PhysicalManifest).where(
                PhysicalManifest.id == manifest_id,
                PhysicalManifest.tenant_id == tenant_id
            )
        )
        return result.scalar_one_or_none()

    async def generate_manifest_pdf(self, manifest_id: UUID, tenant_id: UUID) -> io.BytesIO:
        """Generate a PDF barcode sheet for a manifest."""
        manifest = await self.get_manifest(manifest_id, tenant_id)
        if not manifest:
            raise ValueError(f"Manifest {manifest_id} not found")

        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=LETTER)
        width, height = LETTER

        # Header
        c.setFont("Helvetica-Bold", 24)
        c.drawCentredString(width / 2, height - 1 * inch, "PHYSICAL DOCUMENT MANIFEST")
        
        c.setFont("Helvetica", 12)
        c.drawCentredString(width / 2, height - 1.3 * inch, f"Generated on: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")

        # Barcode
        # Using Code128 for the manifest barcode
        barcode_value = manifest.barcode
        bc = code128.Code128(barcode_value, barHeight=1.5 * inch, barWidth=1.5)
        
        # Draw barcode
        # We need to wrap it in a Drawing to render it to PDF
        d = Drawing(bc.width, bc.height)
        d.add(bc)
        
        # Center the barcode
        renderPDF.draw(d, c, (width - bc.width) / 2, height - 4 * inch)
        
        # Human readable barcode
        c.setFont("Helvetica-Bold", 18)
        c.drawCentredString(width / 2, height - 4.3 * inch, barcode_value)

        # Details Table-like structure
        c.setFont("Helvetica-Bold", 14)
        y_pos = height - 5.5 * inch
        
        details = [
            ("Manifest ID:", str(manifest.id)),
            ("Description:", manifest.description or "N/A"),
            ("Location:", manifest.location_path or "N/A"),
            ("Responsible:", manifest.responsible_person or "N/A"),
        ]

        for label, value in details:
            c.setFont("Helvetica-Bold", 12)
            c.drawString(1.5 * inch, y_pos, label)
            c.setFont("Helvetica", 12)
            c.drawString(3 * inch, y_pos, value)
            y_pos -= 0.3 * inch

        # Instructions
        c.setFont("Helvetica-Oblique", 10)
        c.drawCentredString(width / 2, 1 * inch, "Instructions: Place this sheet on top of the physical unit before scanning.")
        c.drawCentredString(width / 2, 0.8 * inch, "The system will automatically associate subsequent pages with this manifest.")

        c.showPage()
        c.save()
        
        buffer.seek(0)
        return buffer
