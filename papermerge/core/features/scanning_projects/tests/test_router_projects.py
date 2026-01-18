# (c) Copyright Datacraft, 2026
"""
Scanning projects router tests.
"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.features.scanning_projects.models import (
	ScanningProjectModel,
	ProjectPhaseModel,
)
from papermerge.core.tests.types import AuthTestClient


async def test_list_projects_empty(
	auth_api_client: AuthTestClient,
	db_session: AsyncSession,
):
	"""Test listing projects when none exist."""
	response = await auth_api_client.get("/projects/")

	assert response.status_code == 200, response.json()
	data = response.json()
	assert data["items"] == []
	assert data["total"] == 0


async def test_create_project(
	auth_api_client: AuthTestClient,
	db_session: AsyncSession,
):
	"""Test creating a scanning project."""
	count_before = await db_session.scalar(select(func.count(ScanningProjectModel.id)))
	assert count_before == 0

	response = await auth_api_client.post(
		"/projects/",
		json={
			"name": "Archive Digitization",
			"code": "ARCH-2026",
			"description": "Digitize historical archives",
			"status": "planning",
			"estimated_pages": 50000,
			"daily_page_target": 500,
			"priority": "high",
		},
	)

	assert response.status_code == 201, response.json()
	data = response.json()
	assert data["name"] == "Archive Digitization"
	assert data["code"] == "ARCH-2026"
	assert data["status"] == "planning"

	count_after = await db_session.scalar(select(func.count(ScanningProjectModel.id)))
	assert count_after == 1


async def test_get_project(
	auth_api_client: AuthTestClient,
	make_scanning_project,
):
	"""Test getting a single project."""
	project = await make_scanning_project(name="Test Project")

	response = await auth_api_client.get(f"/projects/{project.id}")

	assert response.status_code == 200, response.json()
	data = response.json()
	assert data["id"] == project.id
	assert data["name"] == "Test Project"


async def test_update_project(
	auth_api_client: AuthTestClient,
	make_scanning_project,
):
	"""Test updating a project."""
	project = await make_scanning_project(name="Old Name", status="planning")

	response = await auth_api_client.patch(
		f"/projects/{project.id}",
		json={"name": "New Name", "status": "active"},
	)

	assert response.status_code == 200, response.json()
	data = response.json()
	assert data["name"] == "New Name"
	assert data["status"] == "active"


async def test_delete_project(
	auth_api_client: AuthTestClient,
	make_scanning_project,
	db_session: AsyncSession,
):
	"""Test deleting a project."""
	project = await make_scanning_project()

	count_before = await db_session.scalar(select(func.count(ScanningProjectModel.id)))
	assert count_before == 1

	response = await auth_api_client.delete(f"/projects/{project.id}")

	assert response.status_code == 204

	count_after = await db_session.scalar(select(func.count(ScanningProjectModel.id)))
	assert count_after == 0


async def test_list_projects_pagination(
	auth_api_client: AuthTestClient,
	make_scanning_project,
):
	"""Test paginated project list."""
	for i in range(8):
		await make_scanning_project(name=f"Project {i}")

	response = await auth_api_client.get(
		"/projects/",
		params={"page": 1, "page_size": 5},
	)

	assert response.status_code == 200, response.json()
	data = response.json()
	assert len(data["items"]) == 5
	assert data["total"] == 8


async def test_list_projects_by_status(
	auth_api_client: AuthTestClient,
	make_scanning_project,
):
	"""Test filtering projects by status."""
	await make_scanning_project(name="Active Project", status="active")
	await make_scanning_project(name="Planning Project", status="planning")
	await make_scanning_project(name="Completed Project", status="completed")

	response = await auth_api_client.get(
		"/projects/",
		params={"status": "active"},
	)

	assert response.status_code == 200, response.json()
	data = response.json()
	assert len(data["items"]) == 1
	assert data["items"][0]["name"] == "Active Project"


async def test_create_project_phase(
	auth_api_client: AuthTestClient,
	make_scanning_project,
	db_session: AsyncSession,
):
	"""Test creating a project phase."""
	project = await make_scanning_project()

	count_before = await db_session.scalar(select(func.count(ProjectPhaseModel.id)))
	assert count_before == 0

	response = await auth_api_client.post(
		f"/projects/{project.id}/phases",
		json={
			"name": "Preparation Phase",
			"description": "Initial setup and planning",
			"sequence_order": 1,
			"estimated_pages": 10000,
		},
	)

	assert response.status_code == 201, response.json()
	data = response.json()
	assert data["name"] == "Preparation Phase"
	assert data["sequence_order"] == 1

	count_after = await db_session.scalar(select(func.count(ProjectPhaseModel.id)))
	assert count_after == 1


async def test_get_project_statistics(
	auth_api_client: AuthTestClient,
	make_scanning_project,
	make_scanning_session,
):
	"""Test getting project statistics."""
	project = await make_scanning_project(estimated_pages=1000)
	await make_scanning_session(project=project, pages_scanned=100)
	await make_scanning_session(project=project, pages_scanned=150)

	response = await auth_api_client.get(f"/projects/{project.id}/statistics")

	assert response.status_code == 200, response.json()
	data = response.json()
	assert data["total_pages_scanned"] == 250
	assert data["completion_percentage"] == 25.0  # 250/1000 = 25%
