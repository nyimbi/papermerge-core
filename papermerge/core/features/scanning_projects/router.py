# (c) Copyright Datacraft, 2026
"""FastAPI router for Scanning Projects feature."""
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.auth import get_current_user
from papermerge.core.db.engine import get_db
from papermerge.core.schemas import User

from . import service
from .ai_advisor import get_project_advisor
from .views import (
	ScanningProject,
	ScanningProjectCreate,
	ScanningProjectUpdate,
	ScanningBatch,
	ScanningBatchCreate,
	ScanningBatchUpdate,
	ScanningMilestone,
	ScanningMilestoneCreate,
	ScanningMilestoneUpdate,
	QualityControlSample,
	QualityControlSampleCreate,
	QualityControlSampleUpdate,
	ScanningResource,
	ScanningResourceCreate,
	ScanningResourceUpdate,
	ScanningProjectMetrics,
	# New models
	ProjectPhase,
	ProjectPhaseCreate,
	ProjectPhaseUpdate,
	ScanningSession,
	ScanningSessionCreate,
	ScanningSessionEnd,
	ProgressSnapshot,
	DailyProjectMetrics,
	OperatorDailyMetrics,
	ProjectIssue,
	ProjectIssueCreate,
	ProjectIssueUpdate,
	AIAdvisorResponse,
)

router = APIRouter(prefix="/scanning-projects", tags=["scanning-projects"])


# =====================================================
# Projects Endpoints
# =====================================================


@router.get("", response_model=list[ScanningProject])
async def list_projects(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[ScanningProject]:
	"""List all scanning projects for the current tenant."""
	projects = await service.get_scanning_projects(session, user.tenant_id)
	return list(projects)


@router.get("/{project_id}", response_model=ScanningProject)
async def get_project(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningProject:
	"""Get a scanning project by ID."""
	project = await service.get_scanning_project(session, project_id, user.tenant_id)
	if not project:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
	return project


@router.post("", response_model=ScanningProject, status_code=status.HTTP_201_CREATED)
async def create_project(
	data: ScanningProjectCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningProject:
	"""Create a new scanning project."""
	return await service.create_scanning_project(session, user.tenant_id, data)


@router.patch("/{project_id}", response_model=ScanningProject)
async def update_project(
	project_id: str,
	data: ScanningProjectUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningProject:
	"""Update a scanning project."""
	project = await service.update_scanning_project(session, project_id, user.tenant_id, data)
	if not project:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
	return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
	"""Delete a scanning project."""
	deleted = await service.delete_scanning_project(session, project_id, user.tenant_id)
	if not deleted:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")


@router.get("/{project_id}/metrics", response_model=ScanningProjectMetrics)
async def get_project_metrics(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningProjectMetrics:
	"""Get metrics for a scanning project."""
	return await service.get_project_metrics(session, project_id)


# =====================================================
# Batches Endpoints
# =====================================================


@router.get("/{project_id}/batches", response_model=list[ScanningBatch])
async def list_batches(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[ScanningBatch]:
	"""List all batches for a project."""
	batches = await service.get_project_batches(session, project_id, user.tenant_id)
	return list(batches)


@router.post(
	"/{project_id}/batches",
	response_model=ScanningBatch,
	status_code=status.HTTP_201_CREATED,
)
async def create_batch(
	project_id: str,
	data: ScanningBatchCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningBatch:
	"""Create a new batch for a project."""
	return await service.create_batch(session, project_id, data)


@router.patch("/{project_id}/batches/{batch_id}", response_model=ScanningBatch)
async def update_batch(
	project_id: str,
	batch_id: str,
	data: ScanningBatchUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningBatch:
	"""Update a batch."""
	batch = await service.update_batch(session, batch_id, data)
	if not batch:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
	return batch


@router.post("/{project_id}/batches/{batch_id}/start-scan", response_model=ScanningBatch)
async def start_batch_scan(
	project_id: str,
	batch_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningBatch:
	"""Start scanning a batch."""
	batch = await service.start_batch_scan(session, batch_id)
	if not batch:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
	return batch


@router.post("/{project_id}/batches/{batch_id}/complete-scan", response_model=ScanningBatch)
async def complete_batch_scan(
	project_id: str,
	batch_id: str,
	actual_pages: int,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningBatch:
	"""Complete scanning a batch."""
	batch = await service.complete_batch_scan(session, batch_id, actual_pages)
	if not batch:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
	return batch


# =====================================================
# Milestones Endpoints
# =====================================================


@router.get("/{project_id}/milestones", response_model=list[ScanningMilestone])
async def list_milestones(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[ScanningMilestone]:
	"""List all milestones for a project."""
	milestones = await service.get_project_milestones(session, project_id)
	return list(milestones)


@router.post(
	"/{project_id}/milestones",
	response_model=ScanningMilestone,
	status_code=status.HTTP_201_CREATED,
)
async def create_milestone(
	project_id: str,
	data: ScanningMilestoneCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningMilestone:
	"""Create a new milestone."""
	return await service.create_milestone(session, project_id, data)


@router.patch("/{project_id}/milestones/{milestone_id}", response_model=ScanningMilestone)
async def update_milestone(
	project_id: str,
	milestone_id: str,
	data: ScanningMilestoneUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningMilestone:
	"""Update a milestone."""
	milestone = await service.update_milestone(session, milestone_id, data)
	if not milestone:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Milestone not found")
	return milestone


# =====================================================
# QC Endpoints
# =====================================================


@router.get("/{project_id}/qc/pending", response_model=list[QualityControlSample])
async def list_pending_qc_samples(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[QualityControlSample]:
	"""List pending QC samples for a project."""
	samples = await service.get_pending_qc_samples(session, project_id)
	return list(samples)


@router.post(
	"/{project_id}/qc/samples",
	response_model=QualityControlSample,
	status_code=status.HTTP_201_CREATED,
)
async def create_qc_sample(
	project_id: str,
	data: QualityControlSampleCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> QualityControlSample:
	"""Create a new QC sample."""
	return await service.create_qc_sample(session, data)


@router.patch("/{project_id}/qc/samples/{sample_id}", response_model=QualityControlSample)
async def update_qc_sample(
	project_id: str,
	sample_id: str,
	data: QualityControlSampleUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> QualityControlSample:
	"""Update a QC sample with review results."""
	sample = await service.update_qc_sample(
		session, sample_id, user.id, user.username, data
	)
	if not sample:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sample not found")
	return sample


# =====================================================
# Resources Endpoints
# =====================================================


@router.get("/resources", response_model=list[ScanningResource])
async def list_resources(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[ScanningResource]:
	"""List all scanning resources."""
	resources = await service.get_resources(session, user.tenant_id)
	return list(resources)


@router.post(
	"/resources",
	response_model=ScanningResource,
	status_code=status.HTTP_201_CREATED,
)
async def create_resource(
	data: ScanningResourceCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningResource:
	"""Create a new resource."""
	return await service.create_resource(session, user.tenant_id, data)


@router.patch("/resources/{resource_id}", response_model=ScanningResource)
async def update_resource(
	resource_id: str,
	data: ScanningResourceUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningResource:
	"""Update a resource."""
	resource = await service.update_resource(session, resource_id, user.tenant_id, data)
	if not resource:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
	return resource


@router.delete("/resources/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resource(
	resource_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
	"""Delete a resource."""
	deleted = await service.delete_resource(session, resource_id, user.tenant_id)
	if not deleted:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")


# =====================================================
# Phases Endpoints
# =====================================================


@router.get("/{project_id}/phases", response_model=list[ProjectPhase])
async def list_phases(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[ProjectPhase]:
	"""List all phases for a project."""
	phases = await service.get_project_phases(session, project_id)
	return list(phases)


@router.post(
	"/{project_id}/phases",
	response_model=ProjectPhase,
	status_code=status.HTTP_201_CREATED,
)
async def create_phase(
	project_id: str,
	data: ProjectPhaseCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectPhase:
	"""Create a new phase."""
	return await service.create_phase(session, project_id, data)


@router.patch("/{project_id}/phases/{phase_id}", response_model=ProjectPhase)
async def update_phase(
	project_id: str,
	phase_id: str,
	data: ProjectPhaseUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectPhase:
	"""Update a phase."""
	phase = await service.update_phase(session, phase_id, data)
	if not phase:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Phase not found")
	return phase


@router.delete("/{project_id}/phases/{phase_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_phase(
	project_id: str,
	phase_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
	"""Delete a phase."""
	deleted = await service.delete_phase(session, phase_id)
	if not deleted:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Phase not found")


# =====================================================
# Sessions Endpoints
# =====================================================


@router.get("/{project_id}/sessions", response_model=list[ScanningSession])
async def list_sessions(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	active_only: bool = Query(False, description="Only return active sessions"),
) -> list[ScanningSession]:
	"""List scanning sessions for a project."""
	sessions = await service.get_project_sessions(session, project_id, active_only)
	return list(sessions)


@router.post(
	"/{project_id}/sessions",
	response_model=ScanningSession,
	status_code=status.HTTP_201_CREATED,
)
async def start_session(
	project_id: str,
	data: ScanningSessionCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningSession:
	"""Start a new scanning session."""
	return await service.start_session(session, project_id, data)


@router.post("/{project_id}/sessions/{session_id}/end", response_model=ScanningSession)
async def end_session(
	project_id: str,
	session_id: str,
	data: ScanningSessionEnd,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningSession:
	"""End a scanning session."""
	scan_session = await service.end_session(session, session_id, data)
	if not scan_session:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
	return scan_session


# =====================================================
# Issues Endpoints
# =====================================================


@router.get("/{project_id}/issues", response_model=list[ProjectIssue])
async def list_issues(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	open_only: bool = Query(False, description="Only return open issues"),
) -> list[ProjectIssue]:
	"""List issues for a project."""
	issues = await service.get_project_issues(session, project_id, open_only)
	return list(issues)


@router.post(
	"/{project_id}/issues",
	response_model=ProjectIssue,
	status_code=status.HTTP_201_CREATED,
)
async def create_issue(
	project_id: str,
	data: ProjectIssueCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectIssue:
	"""Create a new issue."""
	return await service.create_issue(session, project_id, user.id, user.username, data)


@router.patch("/{project_id}/issues/{issue_id}", response_model=ProjectIssue)
async def update_issue(
	project_id: str,
	issue_id: str,
	data: ProjectIssueUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectIssue:
	"""Update an issue."""
	issue = await service.update_issue(session, issue_id, data)
	if not issue:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")
	return issue


# =====================================================
# Snapshots & Metrics Endpoints
# =====================================================


@router.post("/{project_id}/snapshots", response_model=ProgressSnapshot)
async def create_snapshot(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProgressSnapshot:
	"""Create a progress snapshot."""
	return await service.create_snapshot(session, project_id)


@router.get("/{project_id}/snapshots", response_model=list[ProgressSnapshot])
async def list_snapshots(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	limit: int = Query(100, ge=1, le=1000),
) -> list[ProgressSnapshot]:
	"""List progress snapshots for a project."""
	snapshots = await service.get_project_snapshots(session, project_id, limit)
	return list(snapshots)


@router.get("/{project_id}/daily-metrics", response_model=list[DailyProjectMetrics])
async def list_daily_metrics(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	start_date: date | None = None,
	end_date: date | None = None,
) -> list[DailyProjectMetrics]:
	"""List daily metrics for a project."""
	metrics = await service.get_daily_metrics(session, project_id, start_date, end_date)
	return list(metrics)


@router.get("/{project_id}/operator-metrics", response_model=list[OperatorDailyMetrics])
async def list_operator_metrics(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	operator_id: str | None = None,
	start_date: date | None = None,
	end_date: date | None = None,
) -> list[OperatorDailyMetrics]:
	"""List operator daily metrics for a project."""
	metrics = await service.get_operator_metrics(
		session, project_id, operator_id, start_date, end_date
	)
	return list(metrics)


# =====================================================
# AI Advisor Endpoints
# =====================================================


@router.get("/{project_id}/ai-analysis", response_model=AIAdvisorResponse)
async def get_ai_analysis(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> AIAdvisorResponse:
	"""Get AI-powered analysis and recommendations for a project."""
	advisor = get_project_advisor()
	return await advisor.analyze_project(session, project_id)


# =====================================================
# Reports Endpoints
# =====================================================


@router.get("/{project_id}/reports/daily")
async def get_daily_report(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	report_date: date | None = None,
	format: str = Query("html", regex="^(html|pdf)$"),
):
	"""Generate a daily progress report."""
	from fastapi.responses import HTMLResponse, Response
	from .reports import generate_daily_report

	content = await generate_daily_report(session, project_id, report_date, format)

	if format == "pdf":
		return Response(
			content=content,
			media_type="application/pdf",
			headers={"Content-Disposition": f"attachment; filename=daily-report-{report_date or 'today'}.pdf"},
		)
	return HTMLResponse(content=content)


@router.get("/{project_id}/reports/weekly")
async def get_weekly_report(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	week_ending: date | None = None,
	format: str = Query("html", regex="^(html|pdf)$"),
):
	"""Generate a weekly summary report."""
	from fastapi.responses import HTMLResponse, Response
	from .reports import generate_weekly_report

	content = await generate_weekly_report(session, project_id, week_ending, format)

	if format == "pdf":
		return Response(
			content=content,
			media_type="application/pdf",
			headers={"Content-Disposition": f"attachment; filename=weekly-report-{week_ending or 'current'}.pdf"},
		)
	return HTMLResponse(content=content)
