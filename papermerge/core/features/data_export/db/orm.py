# (c) Copyright Datacraft, 2026
"""ORM model for data export jobs (GDPR, bundle, full-tenant)."""
from datetime import datetime

from sqlalchemy import String, Text, Integer
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from papermerge.core.db.base import Base
from papermerge.core.utils.tz import utc_now
from papermerge.core.utils.uuid_compat import uuid7str


class DataExportJob(Base):
	"""Tracks async data export jobs.

	job_type values:
	  "full_tenant"    – all documents for a tenant
	  "bundle"         – caller-specified list of documents
	  "gdpr_subject"   – all docs created by a specific user (email)

	status values: "pending" | "processing" | "completed" | "failed"
	"""
	__tablename__ = "data_export_jobs"

	id: Mapped[str] = mapped_column(
		String(36),
		primary_key=True,
		default=uuid7str,
	)
	job_type: Mapped[str] = mapped_column(String(32), nullable=False)
	status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")

	requested_by_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
	tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

	# JSON-serialised params: document_ids, subject_email, include_metadata, …
	params: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

	# Path in object storage once the export is complete (e.g. exports/<id>/export.zip)
	file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
	file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

	error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True),
		nullable=False,
		default=utc_now,
	)
	completed_at: Mapped[datetime | None] = mapped_column(
		TIMESTAMP(timezone=True),
		nullable=True,
	)
