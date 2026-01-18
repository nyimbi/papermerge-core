# (c) Copyright Datacraft, 2026
"""Single-view (hidden) document access service."""
import logging
import os
import hashlib
from uuid import UUID
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from papermerge.core.features.encryption.db.orm import HiddenDocumentAccess

logger = logging.getLogger(__name__)


class SingleViewResult:
	"""Result of single-view operations."""

	def __init__(
		self,
		success: bool,
		access_code: str | None = None,
		document_id: UUID | None = None,
		expires_at: datetime | None = None,
		message: str | None = None,
	):
		self.success = success
		self.access_code = access_code
		self.document_id = document_id
		self.expires_at = expires_at
		self.message = message


class SingleViewService:
	"""Manage single-view access to hidden documents."""

	def __init__(self, db: Session):
		self.db = db

	async def create_single_view_access(
		self,
		document_id: UUID,
		created_by: UUID,
		expires_hours: int = 24,
		max_views: int = 1,
		require_auth: bool = False,
		allowed_actions: list[str] | None = None,
	) -> SingleViewResult:
		"""Create single-view access for a hidden document."""
		# Generate secure access code
		access_code = self._generate_access_code()

		# Calculate expiry
		expires_at = datetime.now(timezone.utc) + timedelta(hours=expires_hours)

		# Create access record
		access = HiddenDocumentAccess(
			document_id=document_id,
			access_code=access_code,
			created_by=created_by,
			expires_at=expires_at,
			max_views=max_views,
			require_auth=require_auth,
			allowed_actions=allowed_actions or ["view"],
		)
		self.db.add(access)
		self.db.commit()
		self.db.refresh(access)

		logger.info(f"Created single-view access for document {document_id}")

		return SingleViewResult(
			success=True,
			access_code=access_code,
			document_id=document_id,
			expires_at=expires_at,
		)

	async def validate_access(
		self,
		access_code: str,
		user_id: UUID | None = None,
	) -> SingleViewResult:
		"""Validate single-view access code."""
		access = await self._get_access_by_code(access_code)

		if not access:
			return SingleViewResult(
				success=False,
				message="Invalid access code",
			)

		now = datetime.now(timezone.utc)

		# Check expiry
		if access.expires_at and access.expires_at < now:
			return SingleViewResult(
				success=False,
				message="Access has expired",
			)

		# Check view count
		if access.max_views and access.view_count >= access.max_views:
			return SingleViewResult(
				success=False,
				message="Maximum views exceeded",
			)

		# Check if revoked
		if access.is_revoked:
			return SingleViewResult(
				success=False,
				message="Access has been revoked",
			)

		# Check auth requirement
		if access.require_auth and not user_id:
			return SingleViewResult(
				success=False,
				message="Authentication required",
			)

		return SingleViewResult(
			success=True,
			access_code=access_code,
			document_id=access.document_id,
			expires_at=access.expires_at,
		)

	async def record_view(
		self,
		access_code: str,
		user_id: UUID | None = None,
		ip_address: str | None = None,
		user_agent: str | None = None,
	) -> bool:
		"""Record a view of a hidden document."""
		access = await self._get_access_by_code(access_code)

		if not access:
			return False

		# Increment view count
		access.view_count = (access.view_count or 0) + 1
		access.last_accessed_at = datetime.now(timezone.utc)

		# Log access details
		access_log = access.access_log or []
		access_log.append({
			"timestamp": datetime.now(timezone.utc).isoformat(),
			"user_id": str(user_id) if user_id else None,
			"ip_address": ip_address,
			"user_agent": user_agent,
		})
		access.access_log = access_log

		self.db.commit()

		logger.info(f"Recorded view for access {access.id}")
		return True

	async def revoke_access(
		self,
		access_code: str,
		revoked_by: UUID,
	) -> bool:
		"""Revoke single-view access."""
		access = await self._get_access_by_code(access_code)

		if not access:
			return False

		access.is_revoked = True
		access.revoked_by = revoked_by
		access.revoked_at = datetime.now(timezone.utc)
		self.db.commit()

		logger.info(f"Revoked access {access.id}")
		return True

	async def get_document_access_history(
		self,
		document_id: UUID,
	) -> list[HiddenDocumentAccess]:
		"""Get all access records for a document."""
		stmt = select(HiddenDocumentAccess).where(
			HiddenDocumentAccess.document_id == document_id
		).order_by(HiddenDocumentAccess.created_at.desc())
		return list(self.db.scalars(stmt))

	async def cleanup_expired_access(self) -> int:
		"""Clean up expired access records."""
		now = datetime.now(timezone.utc)
		stmt = select(HiddenDocumentAccess).where(
			and_(
				HiddenDocumentAccess.expires_at < now,
				HiddenDocumentAccess.is_revoked == False,
			)
		)

		count = 0
		for access in self.db.scalars(stmt):
			access.is_revoked = True
			count += 1

		if count > 0:
			self.db.commit()
			logger.info(f"Cleaned up {count} expired access records")

		return count

	def _generate_access_code(self, length: int = 32) -> str:
		"""Generate a secure random access code."""
		random_bytes = os.urandom(length)
		return hashlib.sha256(random_bytes).hexdigest()[:length]

	async def _get_access_by_code(
		self,
		access_code: str,
	) -> HiddenDocumentAccess | None:
		"""Get access record by code."""
		stmt = select(HiddenDocumentAccess).where(
			HiddenDocumentAccess.access_code == access_code
		)
		return self.db.scalar(stmt)
