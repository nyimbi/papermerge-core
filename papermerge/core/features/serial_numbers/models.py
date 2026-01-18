# Document Serial Number Models
# GitHub Issue #132: Automatically assign document serial numbers after upload
from datetime import datetime, date
from enum import Enum
from typing import Any

from sqlalchemy import (
	Column, String, Integer, Boolean, DateTime, Text, ForeignKey,
	UniqueConstraint, CheckConstraint, Index,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship, Mapped, mapped_column
from uuid_extensions import uuid7str

from papermerge.core.db.base import Base


class ResetFrequency(str, Enum):
	"""When to reset the sequence counter."""
	NEVER = "never"
	DAILY = "daily"
	WEEKLY = "weekly"
	MONTHLY = "monthly"
	YEARLY = "yearly"


class SerialNumberSequence(Base):
	"""
	Serial number sequence configuration.

	Defines patterns and counters for generating document serial numbers.
	Each document type can have its own sequence, or a global default can be used.
	"""
	__tablename__ = "serial_number_sequences"

	id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uuid7str)
	name: Mapped[str] = mapped_column(String(100), nullable=False)
	description: Mapped[str | None] = mapped_column(Text, nullable=True)

	# Pattern for generating serial numbers
	# Supports placeholders: {YEAR}, {MONTH}, {DAY}, {SEQ}, {SEQ:4} (padded), {DOCTYPE}, {PREFIX}
	pattern: Mapped[str] = mapped_column(
		String(200),
		nullable=False,
		default="{PREFIX}-{YEAR}{MONTH}-{SEQ:5}"
	)
	prefix: Mapped[str] = mapped_column(String(20), nullable=False, default="DOC")

	# Current sequence value
	current_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

	# When to reset the counter
	reset_frequency: Mapped[str] = mapped_column(
		String(20),
		nullable=False,
		default=ResetFrequency.YEARLY.value
	)
	last_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

	# Scope - which document types use this sequence
	# NULL = global default, specific ID = per document type
	document_type_id: Mapped[str | None] = mapped_column(
		String(32),
		ForeignKey("document_types.id", ondelete="CASCADE"),
		nullable=True
	)

	# Per-tenant isolation
	tenant_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

	# Settings
	is_active: Mapped[bool] = mapped_column(Boolean, default=True)
	auto_assign: Mapped[bool] = mapped_column(Boolean, default=True)  # Auto-assign on upload
	allow_manual: Mapped[bool] = mapped_column(Boolean, default=True)  # Allow manual override

	# Audit
	created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
	updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
	created_by_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

	__table_args__ = (
		# Only one sequence per document type per tenant
		UniqueConstraint("document_type_id", "tenant_id", name="uq_sequence_doctype_tenant"),
		# Index for lookup
		Index("ix_serial_sequence_doctype", "document_type_id"),
		Index("ix_serial_sequence_tenant", "tenant_id"),
	)

	def generate_next(self, document_type_name: str | None = None) -> str:
		"""
		Generate the next serial number.

		Note: This should be called within a transaction with row locking
		to ensure uniqueness.
		"""
		# Check if reset is needed
		self._check_reset()

		# Increment counter
		self.current_value += 1

		# Generate serial number from pattern
		now = datetime.now()
		serial = self.pattern

		# Replace placeholders
		replacements = {
			"{YEAR}": str(now.year),
			"{YY}": str(now.year)[-2:],
			"{MONTH}": f"{now.month:02d}",
			"{DAY}": f"{now.day:02d}",
			"{WEEK}": f"{now.isocalendar()[1]:02d}",
			"{PREFIX}": self.prefix,
			"{DOCTYPE}": document_type_name or "DOC",
		}

		for placeholder, value in replacements.items():
			serial = serial.replace(placeholder, value)

		# Handle sequence with padding: {SEQ:4} -> 0001
		import re
		seq_match = re.search(r"\{SEQ(?::(\d+))?\}", serial)
		if seq_match:
			padding = int(seq_match.group(1) or 0)
			seq_str = str(self.current_value).zfill(padding) if padding else str(self.current_value)
			serial = re.sub(r"\{SEQ(?::\d+)?\}", seq_str, serial)

		return serial

	def _check_reset(self) -> None:
		"""Check if the counter should be reset based on frequency."""
		if self.reset_frequency == ResetFrequency.NEVER.value:
			return

		now = datetime.now()
		last_reset = self.last_reset_at or self.created_at

		should_reset = False

		if self.reset_frequency == ResetFrequency.DAILY.value:
			should_reset = now.date() > last_reset.date()
		elif self.reset_frequency == ResetFrequency.WEEKLY.value:
			should_reset = now.isocalendar()[1] > last_reset.isocalendar()[1] or now.year > last_reset.year
		elif self.reset_frequency == ResetFrequency.MONTHLY.value:
			should_reset = (now.year, now.month) > (last_reset.year, last_reset.month)
		elif self.reset_frequency == ResetFrequency.YEARLY.value:
			should_reset = now.year > last_reset.year

		if should_reset:
			self.current_value = 0
			self.last_reset_at = now


class DocumentSerialNumber(Base):
	"""
	Assigned serial numbers for documents.

	Stores the mapping between documents and their assigned serial numbers.
	"""
	__tablename__ = "document_serial_numbers"

	id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uuid7str)

	# The document
	document_id: Mapped[str] = mapped_column(
		String(32),
		ForeignKey("nodes.id", ondelete="CASCADE"),
		nullable=False,
		unique=True
	)

	# The serial number
	serial_number: Mapped[str] = mapped_column(String(100), nullable=False)

	# Which sequence generated this
	sequence_id: Mapped[str | None] = mapped_column(
		String(32),
		ForeignKey("serial_number_sequences.id", ondelete="SET NULL"),
		nullable=True
	)

	# The sequence value at time of assignment
	sequence_value: Mapped[int | None] = mapped_column(Integer, nullable=True)

	# Was this manually assigned?
	is_manual: Mapped[bool] = mapped_column(Boolean, default=False)

	# Tenant
	tenant_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

	# Audit
	assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
	assigned_by_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

	__table_args__ = (
		# Serial numbers must be unique within a tenant
		UniqueConstraint("serial_number", "tenant_id", name="uq_serial_number_tenant"),
		# Fast lookup by serial number
		Index("ix_doc_serial_number", "serial_number"),
		Index("ix_doc_serial_tenant", "tenant_id"),
	)
