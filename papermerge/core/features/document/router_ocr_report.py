"""OCR fleet-wide quality-report router.

Auto-discovered by router_loader as router_ocr_report.py.
Exposes GET /ocr/quality-report as a standalone router (prefix=/ocr) so
it is not nested under /documents.

The implementation lives in router_ocr.py; this shim re-exports it under
the name `router` which is the convention expected by router_loader.
"""
from papermerge.core.features.document.router_ocr import ocr_report_router as router  # noqa: F401
