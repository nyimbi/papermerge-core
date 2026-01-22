# (c) Copyright Datacraft, 2026
"""
Scanning projects feature test fixtures.
"""
import pytest
from papermerge.core.utils.uuid_compat import uuid7str
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date

from papermerge.core.features.scanning_projects.models import (
	ScanningProjectModel,
	ProjectPhaseModel,
	ScanningSessionModel,
)


@pytest.fixture
async def make_scanning_project(db_session: AsyncSession, user):
	"""Factory fixture for creating scanning projects."""
	async def _make_scanning_project(
		name: str = "Test Project",
		code: str | None = None,
		**kwargs,
	) -> ScanningProjectModel:
		project = ScanningProjectModel(
			id=uuid7str(),
			owner_id=user.id,
			code=code or f"PRJ-{uuid7str()[:6].upper()}",
			name=name,
			description=kwargs.get("description"),
			status=kwargs.get("status", "planning"),
			start_date=kwargs.get("start_date"),
			target_end_date=kwargs.get("target_end_date"),
			estimated_pages=kwargs.get("estimated_pages"),
			daily_page_target=kwargs.get("daily_page_target"),
			priority=kwargs.get("priority", "medium"),
		)
		db_session.add(project)
		await db_session.commit()
		await db_session.refresh(project)
		return project

	return _make_scanning_project


@pytest.fixture
async def make_project_phase(db_session: AsyncSession, make_scanning_project):
	"""Factory fixture for creating project phases."""
	async def _make_project_phase(
		name: str = "Phase 1",
		project: ScanningProjectModel | None = None,
		**kwargs,
	) -> ProjectPhaseModel:
		if project is None:
			project = await make_scanning_project()

		phase = ProjectPhaseModel(
			id=uuid7str(),
			project_id=project.id,
			name=name,
			description=kwargs.get("description"),
			sequence_order=kwargs.get("sequence_order", 1),
			status=kwargs.get("status", "pending"),
			estimated_pages=kwargs.get("estimated_pages"),
		)
		db_session.add(phase)
		await db_session.commit()
		await db_session.refresh(phase)
		return phase

	return _make_project_phase


@pytest.fixture
async def make_scanning_session(db_session: AsyncSession, user, make_scanning_project):
	"""Factory fixture for creating scanning sessions."""
	async def _make_scanning_session(
		project: ScanningProjectModel | None = None,
		**kwargs,
	) -> ScanningSessionModel:
		if project is None:
			project = await make_scanning_project()

		session = ScanningSessionModel(
			id=uuid7str(),
			project_id=project.id,
			operator_id=user.id,
			scanner_id=kwargs.get("scanner_id"),
			status=kwargs.get("status", "completed"),
			documents_scanned=kwargs.get("documents_scanned", 10),
			pages_scanned=kwargs.get("pages_scanned", 50),
			errors_count=kwargs.get("errors_count", 0),
			quality_score=kwargs.get("quality_score"),
			notes=kwargs.get("notes"),
		)
		db_session.add(session)
		await db_session.commit()
		await db_session.refresh(session)
		return session

	return _make_scanning_session
