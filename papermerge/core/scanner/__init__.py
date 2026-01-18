# (c) Copyright Datacraft, 2026
"""Scanner integration module supporting eSCL/AirScan and SANE."""
from .base import Scanner, ScanJob, ScanResult, ScanOptions, ScannerProtocol
from .capabilities import ScannerCapabilities, ColorMode, InputSource, Resolution
from .discovery import ScannerDiscovery, DiscoveredScanner
from .escl import ESCLScanner
from .sane import SANEScanner

__all__ = [
	'Scanner',
	'ScanJob',
	'ScanResult',
	'ScanOptions',
	'ScannerProtocol',
	'ScannerCapabilities',
	'ColorMode',
	'InputSource',
	'Resolution',
	'ScannerDiscovery',
	'DiscoveredScanner',
	'ESCLScanner',
	'SANEScanner',
]
