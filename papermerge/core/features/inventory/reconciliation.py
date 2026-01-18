# (c) Copyright Datacraft, 2026
"""
Inventory reconciliation between physical and digital records.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from papermerge.core.logging import get_logger

logger = get_logger(__name__)


class DiscrepancyType(str, Enum):
	"""Types of inventory discrepancies."""
	MISSING_DIGITAL = "missing_digital"  # Physical exists, no digital
	MISSING_PHYSICAL = "missing_physical"  # Digital exists, no physical
	LOCATION_MISMATCH = "location_mismatch"  # Different locations
	COUNT_MISMATCH = "count_mismatch"  # Page count differs
	QUALITY_ISSUE = "quality_issue"  # Digital needs rescan
	DUPLICATE_FOUND = "duplicate_found"  # Unexpected duplicate
	METADATA_MISMATCH = "metadata_mismatch"  # Metadata doesn't match


class DiscrepancySeverity(str, Enum):
	"""Severity levels for discrepancies."""
	INFO = "info"
	WARNING = "warning"
	ERROR = "error"
	CRITICAL = "critical"


@dataclass
class PhysicalRecord:
	"""Record of physical document inventory."""
	barcode: str
	location_code: str
	box_label: str | None = None
	folder_label: str | None = None
	sequence_number: int | None = None
	description: str | None = None
	page_count: int | None = None
	scanned_at: datetime | None = None
	scanned_by: str | None = None
	notes: str | None = None
	metadata: dict | None = None


@dataclass
class DigitalRecord:
	"""Record of digital document."""
	document_id: str
	provenance_id: str | None = None
	batch_id: str | None = None
	barcode: str | None = None
	location_code: str | None = None
	box_label: str | None = None
	folder_label: str | None = None
	page_count: int | None = None
	quality_score: float | None = None
	file_hash: str | None = None
	created_at: datetime | None = None
	metadata: dict | None = None


@dataclass
class Discrepancy:
	"""Represents an inventory discrepancy."""
	id: str
	discrepancy_type: DiscrepancyType
	severity: DiscrepancySeverity
	physical_record: PhysicalRecord | None = None
	digital_record: DigitalRecord | None = None
	description: str = ""
	suggested_action: str = ""
	resolved: bool = False
	resolved_at: datetime | None = None
	resolved_by: str | None = None
	resolution_notes: str | None = None


@dataclass
class ReconciliationReport:
	"""Report from reconciliation process."""
	id: str
	started_at: datetime
	completed_at: datetime | None = None
	status: Literal["in_progress", "completed", "failed"] = "in_progress"

	# Counts
	total_physical: int = 0
	total_digital: int = 0
	matched: int = 0
	discrepancies_found: int = 0

	# Discrepancies by type
	discrepancies: list[Discrepancy] = field(default_factory=list)

	# Summary
	missing_digital_count: int = 0
	missing_physical_count: int = 0
	location_mismatch_count: int = 0
	other_issues_count: int = 0

	# Error info
	error_message: str | None = None


class InventoryReconciler:
	"""
	Reconcile physical inventory with digital records.

	Identifies discrepancies between what exists physically
	and what has been digitized.
	"""

	def __init__(
		self,
		match_by: list[str] | None = None,
		page_count_tolerance: int = 0,
		require_quality_check: bool = True,
		min_quality_score: float = 70.0,
	):
		"""
		Initialize reconciler.

		Args:
			match_by: Fields to match on (default: barcode, location_code)
			page_count_tolerance: Allowed difference in page counts
			require_quality_check: Flag quality issues as discrepancies
			min_quality_score: Minimum acceptable quality score
		"""
		self.match_by = match_by or ["barcode"]
		self.page_count_tolerance = page_count_tolerance
		self.require_quality_check = require_quality_check
		self.min_quality_score = min_quality_score

	async def reconcile(
		self,
		physical_records: list[PhysicalRecord],
		digital_records: list[DigitalRecord],
		report_id: str | None = None,
	) -> ReconciliationReport:
		"""
		Perform reconciliation between physical and digital records.

		Args:
			physical_records: List of physical inventory records
			digital_records: List of digital document records
			report_id: Optional ID for the report

		Returns:
			ReconciliationReport with discrepancies
		"""
		from uuid_extensions import uuid7str

		report = ReconciliationReport(
			id=report_id or uuid7str(),
			started_at=datetime.utcnow(),
			total_physical=len(physical_records),
			total_digital=len(digital_records),
		)

		# Build lookup index for digital records
		digital_index = self._build_index(digital_records, self.match_by)

		# Track which digital records were matched
		matched_digital_ids = set()
		discrepancies = []

		# Check each physical record
		for physical in physical_records:
			match_key = self._get_match_key(physical, self.match_by)

			if match_key in digital_index:
				digital = digital_index[match_key]
				matched_digital_ids.add(digital.document_id)
				report.matched += 1

				# Check for other discrepancies
				issues = self._check_record_match(physical, digital)
				discrepancies.extend(issues)
			else:
				# Physical exists but no digital
				discrepancies.append(Discrepancy(
					id=uuid7str(),
					discrepancy_type=DiscrepancyType.MISSING_DIGITAL,
					severity=DiscrepancySeverity.ERROR,
					physical_record=physical,
					description=f"Physical document with barcode {physical.barcode} not found in digital records",
					suggested_action="Scan and digitize this document",
				))

		# Check for digital records without physical counterparts
		for digital in digital_records:
			if digital.document_id not in matched_digital_ids:
				discrepancies.append(Discrepancy(
					id=uuid7str(),
					discrepancy_type=DiscrepancyType.MISSING_PHYSICAL,
					severity=DiscrepancySeverity.WARNING,
					digital_record=digital,
					description=f"Digital document {digital.document_id} has no matching physical record",
					suggested_action="Verify physical document location or update digital record metadata",
				))

		# Summarize
		report.discrepancies = discrepancies
		report.discrepancies_found = len(discrepancies)
		report.missing_digital_count = sum(
			1 for d in discrepancies
			if d.discrepancy_type == DiscrepancyType.MISSING_DIGITAL
		)
		report.missing_physical_count = sum(
			1 for d in discrepancies
			if d.discrepancy_type == DiscrepancyType.MISSING_PHYSICAL
		)
		report.location_mismatch_count = sum(
			1 for d in discrepancies
			if d.discrepancy_type == DiscrepancyType.LOCATION_MISMATCH
		)
		report.other_issues_count = (
			report.discrepancies_found
			- report.missing_digital_count
			- report.missing_physical_count
			- report.location_mismatch_count
		)

		report.completed_at = datetime.utcnow()
		report.status = "completed"

		return report

	def _build_index(
		self,
		records: list[DigitalRecord],
		match_by: list[str],
	) -> dict[str, DigitalRecord]:
		"""Build lookup index from records."""
		index = {}
		for record in records:
			key = self._get_match_key(record, match_by)
			if key:
				index[key] = record
		return index

	def _get_match_key(
		self,
		record: PhysicalRecord | DigitalRecord,
		match_by: list[str],
	) -> str | None:
		"""Generate match key from record fields."""
		parts = []
		for field_name in match_by:
			value = getattr(record, field_name, None)
			if value:
				parts.append(str(value))
		return "|".join(parts) if parts else None

	def _check_record_match(
		self,
		physical: PhysicalRecord,
		digital: DigitalRecord,
	) -> list[Discrepancy]:
		"""Check matched records for other discrepancies."""
		from uuid_extensions import uuid7str

		issues = []

		# Check location match
		if (physical.location_code and digital.location_code and
				physical.location_code != digital.location_code):
			issues.append(Discrepancy(
				id=uuid7str(),
				discrepancy_type=DiscrepancyType.LOCATION_MISMATCH,
				severity=DiscrepancySeverity.WARNING,
				physical_record=physical,
				digital_record=digital,
				description=(
					f"Location mismatch: physical={physical.location_code}, "
					f"digital={digital.location_code}"
				),
				suggested_action="Update location metadata in digital record",
			))

		# Check page count
		if (physical.page_count is not None and digital.page_count is not None):
			diff = abs(physical.page_count - digital.page_count)
			if diff > self.page_count_tolerance:
				issues.append(Discrepancy(
					id=uuid7str(),
					discrepancy_type=DiscrepancyType.COUNT_MISMATCH,
					severity=DiscrepancySeverity.ERROR,
					physical_record=physical,
					digital_record=digital,
					description=(
						f"Page count mismatch: physical={physical.page_count}, "
						f"digital={digital.page_count}"
					),
					suggested_action="Verify all pages were scanned",
				))

		# Check quality
		if (self.require_quality_check and digital.quality_score is not None
				and digital.quality_score < self.min_quality_score):
			issues.append(Discrepancy(
				id=uuid7str(),
				discrepancy_type=DiscrepancyType.QUALITY_ISSUE,
				severity=DiscrepancySeverity.WARNING,
				physical_record=physical,
				digital_record=digital,
				description=(
					f"Quality score {digital.quality_score:.1f} below threshold "
					f"{self.min_quality_score}"
				),
				suggested_action="Consider rescanning at higher quality",
			))

		return issues

	async def resolve_discrepancy(
		self,
		discrepancy: Discrepancy,
		resolution_notes: str,
		resolved_by: str,
	) -> Discrepancy:
		"""Mark a discrepancy as resolved."""
		discrepancy.resolved = True
		discrepancy.resolved_at = datetime.utcnow()
		discrepancy.resolved_by = resolved_by
		discrepancy.resolution_notes = resolution_notes
		return discrepancy
