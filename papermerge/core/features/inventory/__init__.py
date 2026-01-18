# (c) Copyright Datacraft, 2026
"""
Physical inventory management module.

Provides:
- QR/Data Matrix code generation for physical document tracking
- Duplicate detection using perceptual hashing
- Inventory reconciliation between physical and digital records
"""
from .qr import QRCodeGenerator, DataMatrixGenerator
from .duplicates import DuplicateDetector
from .reconciliation import InventoryReconciler

__all__ = [
	'QRCodeGenerator',
	'DataMatrixGenerator',
	'DuplicateDetector',
	'InventoryReconciler',
]
