# Document Serial Number Service
# GitHub Issue #132: Automatically assign document serial numbers after upload
import logging
from typing import Annotated

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from .models import SerialNumberSequence, DocumentSerialNumber, ResetFrequency
from .views import (
	SerialNumberSequenceCreate, SerialNumberSequenceUpdate,
	SerialNumberSequenceOut, DocumentSerialNumberOut,
	ManualSerialAssignment,
)

logger = logging.getLogger(__name__)


class SerialNumberError(Exception):
	"""Serial number operation error."""
	pass


class DuplicateSerialNumberError(SerialNumberError):
	"""Serial number already exists."""
	pass


class SerialNumberService:
	"""Service for managing document serial numbers."""

	def __init__(self, session: AsyncSession):
		self.session = session

	async def get_sequence(
		self,
		sequence_id: str,
		tenant_id: str | None = None,
	) -> SerialNumberSequence | None:
		"""Get a sequence by ID."""
		stmt = select(SerialNumberSequence).where(
			SerialNumberSequence.id == sequence_id
		)
		if tenant_id:
			stmt = stmt.where(SerialNumberSequence.tenant_id == tenant_id)

		result = await self.session.execute(stmt)
		return result.scalar_one_or_none()

	async def get_sequence_for_document_type(
		self,
		document_type_id: str | None,
		tenant_id: str | None = None,
	) -> SerialNumberSequence | None:
		"""
		Get the sequence for a document type.

		Falls back to global default if no specific sequence exists.
		"""
		# First try document-type specific
		if document_type_id:
			stmt = select(SerialNumberSequence).where(
				SerialNumberSequence.document_type_id == document_type_id,
				SerialNumberSequence.is_active == True,
			)
			if tenant_id:
				stmt = stmt.where(SerialNumberSequence.tenant_id == tenant_id)

			result = await self.session.execute(stmt)
			sequence = result.scalar_one_or_none()
			if sequence:
				return sequence

		# Fall back to global default (no document_type_id)
		stmt = select(SerialNumberSequence).where(
			SerialNumberSequence.document_type_id.is_(None),
			SerialNumberSequence.is_active == True,
		)
		if tenant_id:
			stmt = stmt.where(SerialNumberSequence.tenant_id == tenant_id)

		result = await self.session.execute(stmt)
		return result.scalar_one_or_none()

	async def list_sequences(
		self,
		tenant_id: str | None = None,
		include_inactive: bool = False,
	) -> list[SerialNumberSequence]:
		"""List all sequences."""
		stmt = select(SerialNumberSequence)

		if tenant_id:
			stmt = stmt.where(SerialNumberSequence.tenant_id == tenant_id)
		if not include_inactive:
			stmt = stmt.where(SerialNumberSequence.is_active == True)

		stmt = stmt.order_by(SerialNumberSequence.name)

		result = await self.session.execute(stmt)
		return list(result.scalars().all())

	async def create_sequence(
		self,
		data: SerialNumberSequenceCreate,
		tenant_id: str | None = None,
		created_by_id: str | None = None,
	) -> SerialNumberSequence:
		"""Create a new serial number sequence."""
		sequence = SerialNumberSequence(
			name=data.name,
			description=data.description,
			pattern=data.pattern,
			prefix=data.prefix,
			reset_frequency=data.reset_frequency,
			document_type_id=data.document_type_id,
			tenant_id=tenant_id,
			auto_assign=data.auto_assign,
			allow_manual=data.allow_manual,
			created_by_id=created_by_id,
		)

		self.session.add(sequence)
		await self.session.flush()

		logger.info(f"Created serial number sequence: {sequence.name} ({sequence.id})")
		return sequence

	async def update_sequence(
		self,
		sequence_id: str,
		data: SerialNumberSequenceUpdate,
		tenant_id: str | None = None,
	) -> SerialNumberSequence | None:
		"""Update a serial number sequence."""
		sequence = await self.get_sequence(sequence_id, tenant_id)
		if not sequence:
			return None

		update_data = data.model_dump(exclude_unset=True)
		for key, value in update_data.items():
			setattr(sequence, key, value)

		sequence.updated_at = __import__("datetime").datetime.utcnow()
		await self.session.flush()

		logger.info(f"Updated serial number sequence: {sequence.name}")
		return sequence

	async def delete_sequence(
		self,
		sequence_id: str,
		tenant_id: str | None = None,
	) -> bool:
		"""Delete a serial number sequence."""
		sequence = await self.get_sequence(sequence_id, tenant_id)
		if not sequence:
			return False

		await self.session.delete(sequence)
		await self.session.flush()

		logger.info(f"Deleted serial number sequence: {sequence_id}")
		return True

	async def generate_serial_number(
		self,
		document_id: str,
		document_type_id: str | None = None,
		document_type_name: str | None = None,
		tenant_id: str | None = None,
		assigned_by_id: str | None = None,
	) -> DocumentSerialNumber:
		"""
		Generate and assign a serial number to a document.

		Uses row-level locking to ensure uniqueness.
		"""
		# Get the appropriate sequence
		sequence = await self.get_sequence_for_document_type(document_type_id, tenant_id)
		if not sequence:
			raise SerialNumberError("No serial number sequence configured")

		if not sequence.auto_assign:
			raise SerialNumberError("Auto-assignment is disabled for this sequence")

		# Lock the sequence row for update
		stmt = (
			select(SerialNumberSequence)
			.where(SerialNumberSequence.id == sequence.id)
			.with_for_update()
		)
		result = await self.session.execute(stmt)
		sequence = result.scalar_one()

		# Generate the serial number
		serial = sequence.generate_next(document_type_name)

		# Create the assignment
		assignment = DocumentSerialNumber(
			document_id=document_id,
			serial_number=serial,
			sequence_id=sequence.id,
			sequence_value=sequence.current_value,
			is_manual=False,
			tenant_id=tenant_id,
			assigned_by_id=assigned_by_id,
		)

		self.session.add(assignment)
		await self.session.flush()

		logger.info(f"Assigned serial number {serial} to document {document_id}")
		return assignment

	async def assign_manual_serial(
		self,
		data: ManualSerialAssignment,
		tenant_id: str | None = None,
		assigned_by_id: str | None = None,
	) -> DocumentSerialNumber:
		"""Manually assign a serial number to a document."""
		# Check for duplicates
		existing = await self.get_document_by_serial(data.serial_number, tenant_id)
		if existing:
			raise DuplicateSerialNumberError(
				f"Serial number {data.serial_number} is already assigned"
			)

		# Check if document already has a serial
		current = await self.get_serial_for_document(data.document_id)
		if current:
			# Update existing
			current.serial_number = data.serial_number
			current.is_manual = True
			current.assigned_by_id = assigned_by_id
			await self.session.flush()
			return current

		# Create new assignment
		assignment = DocumentSerialNumber(
			document_id=data.document_id,
			serial_number=data.serial_number,
			sequence_id=None,
			is_manual=True,
			tenant_id=tenant_id,
			assigned_by_id=assigned_by_id,
		)

		self.session.add(assignment)
		await self.session.flush()

		logger.info(f"Manually assigned serial number {data.serial_number} to document {data.document_id}")
		return assignment

	async def get_serial_for_document(
		self,
		document_id: str,
	) -> DocumentSerialNumber | None:
		"""Get the serial number assigned to a document."""
		stmt = select(DocumentSerialNumber).where(
			DocumentSerialNumber.document_id == document_id
		)
		result = await self.session.execute(stmt)
		return result.scalar_one_or_none()

	async def get_document_by_serial(
		self,
		serial_number: str,
		tenant_id: str | None = None,
	) -> DocumentSerialNumber | None:
		"""Find a document by its serial number."""
		stmt = select(DocumentSerialNumber).where(
			DocumentSerialNumber.serial_number == serial_number
		)
		if tenant_id:
			stmt = stmt.where(DocumentSerialNumber.tenant_id == tenant_id)

		result = await self.session.execute(stmt)
		return result.scalar_one_or_none()

	async def search_by_serial(
		self,
		query: str,
		tenant_id: str | None = None,
		limit: int = 20,
	) -> list[DocumentSerialNumber]:
		"""Search documents by serial number prefix/pattern."""
		stmt = select(DocumentSerialNumber).where(
			DocumentSerialNumber.serial_number.ilike(f"{query}%")
		)
		if tenant_id:
			stmt = stmt.where(DocumentSerialNumber.tenant_id == tenant_id)

		stmt = stmt.order_by(DocumentSerialNumber.serial_number).limit(limit)

		result = await self.session.execute(stmt)
		return list(result.scalars().all())

	async def remove_serial(
		self,
		document_id: str,
	) -> bool:
		"""Remove serial number from a document."""
		assignment = await self.get_serial_for_document(document_id)
		if not assignment:
			return False

		await self.session.delete(assignment)
		await self.session.flush()

		logger.info(f"Removed serial number from document {document_id}")
		return True


# Dependency injection helper
async def get_serial_service(session: AsyncSession) -> SerialNumberService:
	"""Get serial number service instance."""
	return SerialNumberService(session)
