# (c) Copyright Datacraft, 2026
"""SQLAlchemy ORM model for document retention policies."""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text

from papermerge.core.db.base import Base
from papermerge.core.utils.uuid_compat import uuid7str


class RetentionPolicy(Base):
	"""Defines an automated retention rule that archives, deletes, or moves documents."""
	__tablename__ = "retention_policies"

	id = Column(String(36), primary_key=True, default=uuid7str)
	name = Column(String(255), nullable=False)
	description = Column(Text, nullable=True)

	# "archive" | "delete" | "move"
	policy_type = Column(String(20), nullable=False)

	# Apply N days after document creation
	after_days = Column(Integer, nullable=False)

	# Optional scope — if both are None the policy applies to all documents in the tenant
	applies_to_project_id = Column(
		String(36),
		ForeignKey("scanning_projects.id", ondelete="SET NULL"),
		nullable=True,
	)
	applies_to_document_type = Column(String(255), nullable=True)

	# For "move" policy type — target folder node id
	destination_folder_id = Column(String(36), nullable=True)

	is_active = Column(Boolean, nullable=False, default=True)

	tenant_id = Column(
		String(36),
		ForeignKey("tenants.id", ondelete="CASCADE"),
		nullable=False,
	)
	created_by_id = Column(
		String(36),
		ForeignKey("users.id", ondelete="SET NULL"),
		nullable=True,
	)
	created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
	last_run_at = Column(DateTime, nullable=True)
	docs_processed = Column(Integer, nullable=False, default=0)

	__table_args__ = (
		Index("ix_retention_policies_tenant_active", "tenant_id", "is_active"),
		Index("ix_retention_policies_project", "applies_to_project_id"),
	)
