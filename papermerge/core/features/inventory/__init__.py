# (c) Copyright Datacraft, 2026
"""
Physical inventory management module.

Provides:
- QR/Data Matrix code generation for physical document tracking
- Duplicate detection using perceptual hashing
- Inventory reconciliation between physical and digital records
"""


def __getattr__(name):
	"""Lazy loading to avoid import errors when optional dependencies are missing."""
	if name == 'QRCodeGenerator':
		from .qr import QRCodeGenerator
		return QRCodeGenerator
	elif name == 'DataMatrixGenerator':
		from .qr import DataMatrixGenerator
		return DataMatrixGenerator
	elif name == 'DuplicateDetector':
		from .duplicates import DuplicateDetector
		return DuplicateDetector
	elif name == 'InventoryReconciler':
		from .reconciliation import InventoryReconciler
		return InventoryReconciler
	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
	'QRCodeGenerator',
	'DataMatrixGenerator',
	'DuplicateDetector',
	'InventoryReconciler',
]
