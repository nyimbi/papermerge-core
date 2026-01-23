# (c) Copyright Datacraft, 2026
"""Scanner integration module supporting eSCL/AirScan, SANE, and WSD."""
from .base import Scanner, ScanJob, ScanResult, ScanOptions, ScannerProtocol
from .capabilities import ScannerCapabilities, ColorMode, InputSource, Resolution
from .discovery import ScannerDiscovery, DiscoveredScanner
from .escl import ESCLScanner
from .sane import SANEScanner
from .wsd import WSDScanner
from .quirks import DeviceQuirks, QuirkFlag, detect_quirks


def create_scanner(
	protocol: str | ScannerProtocol,
	**kwargs
) -> Scanner:
	"""
	Factory function to create scanner instances.
	
	Args:
		protocol: Scanner protocol ('escl', 'sane', 'wsd')
		**kwargs: Protocol-specific arguments
		
	Returns:
		Scanner instance for the specified protocol
		
	Raises:
		ValueError: If protocol is not supported
	"""
	if isinstance(protocol, ScannerProtocol):
		protocol = protocol.value
	
	protocol = protocol.lower()
	
	if protocol == 'escl':
		return ESCLScanner(**kwargs)
	elif protocol == 'sane':
		return SANEScanner(**kwargs)
	elif protocol == 'wsd':
		return WSDScanner(**kwargs)
	else:
		raise ValueError(f"Unknown scanner protocol: {protocol}")


__all__ = [
	# Base classes
	'Scanner',
	'ScanJob',
	'ScanResult',
	'ScanOptions',
	'ScannerProtocol',
	# Capabilities
	'ScannerCapabilities',
	'ColorMode',
	'InputSource',
	'Resolution',
	# Discovery
	'ScannerDiscovery',
	'DiscoveredScanner',
	# Protocol implementations
	'ESCLScanner',
	'SANEScanner',
	'WSDScanner',
	# Quirks system
	'DeviceQuirks',
	'QuirkFlag',
	'detect_quirks',
	# Factory
	'create_scanner',
]
