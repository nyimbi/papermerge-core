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
	# Enterprise-scale models
	SubProject,
	SubProjectCreate,
	SubProjectUpdate,
	ScanningLocation,
	ScanningLocationCreate,
	ScanningLocationUpdate,
	Shift,
	ShiftCreate,
	ShiftUpdate,
	ShiftAssignment,
	ShiftAssignmentCreate,
	ProjectCost,
	ProjectCostCreate,
	ProjectBudget,
	ProjectBudgetCreate,
	ProjectBudgetUpdate,
	CostSummary,
	CostType,
	SLA,
	SLACreate,
	SLAUpdate,
	SLAAlert,
	EquipmentMaintenance,
	EquipmentMaintenanceCreate,
	EquipmentMaintenanceUpdate,
	MaintenanceStatus,
	OperatorCertification,
	OperatorCertificationCreate,
	OperatorCertificationUpdate,
	CapacityPlan,
	CapacityPlanCreate,
	DocumentTypeDistribution,
	DocumentTypeDistributionCreate,
	DocumentTypeDistributionUpdate,
	BatchPriority,
	BatchPriorityCreate,
	BatchPriorityUpdate,
	ProjectContract,
	ProjectContractCreate,
	ProjectContractUpdate,
	WorkloadForecast,
	ProjectCheckpoint,
	ProjectCheckpointCreate,
	ProjectCheckpointUpdate,
	BulkBatchImport,
	BulkBatchUpdate,
	BulkOperationResult,
	ProjectDashboard,
	BurndownChart,
	VelocityChart,
	MultiLocationDashboard,
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


# =====================================================
# Sub-Project Endpoints
# =====================================================


@router.get("/{project_id}/sub-projects", response_model=list[SubProject])
async def list_sub_projects(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[SubProject]:
	"""List all sub-projects for a project."""
	sub_projects = await service.get_sub_projects(session, project_id)
	return list(sub_projects)


@router.get("/{project_id}/sub-projects/{sub_project_id}", response_model=SubProject)
async def get_sub_project(
	project_id: str,
	sub_project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> SubProject:
	"""Get a sub-project by ID."""
	sub_project = await service.get_sub_project(session, sub_project_id)
	if not sub_project:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sub-project not found")
	return sub_project


@router.post(
	"/{project_id}/sub-projects",
	response_model=SubProject,
	status_code=status.HTTP_201_CREATED,
)
async def create_sub_project(
	project_id: str,
	data: SubProjectCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> SubProject:
	"""Create a new sub-project."""
	return await service.create_sub_project(session, project_id, data)


@router.patch("/{project_id}/sub-projects/{sub_project_id}", response_model=SubProject)
async def update_sub_project(
	project_id: str,
	sub_project_id: str,
	data: SubProjectUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> SubProject:
	"""Update a sub-project."""
	sub_project = await service.update_sub_project(session, sub_project_id, data)
	if not sub_project:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sub-project not found")
	return sub_project


@router.delete("/{project_id}/sub-projects/{sub_project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sub_project(
	project_id: str,
	sub_project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
	"""Delete a sub-project."""
	deleted = await service.delete_sub_project(session, sub_project_id)
	if not deleted:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sub-project not found")


# =====================================================
# Location Endpoints
# =====================================================


@router.get("/locations", response_model=list[ScanningLocation])
async def list_locations(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	active_only: bool = Query(True, description="Only return active locations"),
) -> list[ScanningLocation]:
	"""List all scanning locations for the tenant."""
	locations = await service.get_locations(session, user.tenant_id, active_only)
	return list(locations)


@router.get("/locations/{location_id}", response_model=ScanningLocation)
async def get_location(
	location_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningLocation:
	"""Get a location by ID."""
	location = await service.get_location(session, location_id, user.tenant_id)
	if not location:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Location not found")
	return location


@router.post(
	"/locations",
	response_model=ScanningLocation,
	status_code=status.HTTP_201_CREATED,
)
async def create_location(
	data: ScanningLocationCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningLocation:
	"""Create a new scanning location."""
	return await service.create_location(session, user.tenant_id, data)


@router.patch("/locations/{location_id}", response_model=ScanningLocation)
async def update_location(
	location_id: str,
	data: ScanningLocationUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningLocation:
	"""Update a location."""
	location = await service.update_location(session, location_id, user.tenant_id, data)
	if not location:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Location not found")
	return location


@router.delete("/locations/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_location(
	location_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
	"""Delete a location."""
	deleted = await service.delete_location(session, location_id, user.tenant_id)
	if not deleted:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Location not found")


# =====================================================
# Shift Endpoints
# =====================================================


@router.get("/shifts", response_model=list[Shift])
async def list_shifts(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	location_id: str | None = None,
	active_only: bool = Query(True),
) -> list[Shift]:
	"""List all shifts for the tenant."""
	shifts = await service.get_shifts(session, user.tenant_id, location_id, active_only)
	return list(shifts)


@router.post(
	"/shifts",
	response_model=Shift,
	status_code=status.HTTP_201_CREATED,
)
async def create_shift(
	data: ShiftCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> Shift:
	"""Create a new shift."""
	return await service.create_shift(session, user.tenant_id, data)


@router.patch("/shifts/{shift_id}", response_model=Shift)
async def update_shift(
	shift_id: str,
	data: ShiftUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> Shift:
	"""Update a shift."""
	shift = await service.update_shift(session, shift_id, user.tenant_id, data)
	if not shift:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shift not found")
	return shift


@router.get("/shift-assignments", response_model=list[ShiftAssignment])
async def list_shift_assignments(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	shift_id: str | None = None,
	operator_id: str | None = None,
	assignment_date: date | None = None,
) -> list[ShiftAssignment]:
	"""List shift assignments with optional filters."""
	assignments = await service.get_shift_assignments(
		session, shift_id, operator_id, assignment_date
	)
	return list(assignments)


@router.post(
	"/shift-assignments",
	response_model=ShiftAssignment,
	status_code=status.HTTP_201_CREATED,
)
async def create_shift_assignment(
	data: ShiftAssignmentCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ShiftAssignment:
	"""Assign an operator to a shift."""
	return await service.create_shift_assignment(session, data)


# =====================================================
# Cost Tracking Endpoints
# =====================================================


@router.get("/{project_id}/costs", response_model=list[ProjectCost])
async def list_project_costs(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	cost_type: CostType | None = None,
	start_date: date | None = None,
	end_date: date | None = None,
) -> list[ProjectCost]:
	"""List costs for a project."""
	costs = await service.get_project_costs(session, project_id, cost_type, start_date, end_date)
	return list(costs)


@router.post(
	"/{project_id}/costs",
	response_model=ProjectCost,
	status_code=status.HTTP_201_CREATED,
)
async def add_project_cost(
	project_id: str,
	data: ProjectCostCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectCost:
	"""Add a cost entry to a project."""
	return await service.add_project_cost(session, project_id, data)


@router.get("/{project_id}/costs/summary", response_model=CostSummary)
async def get_cost_summary(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> CostSummary:
	"""Get cost summary for a project."""
	return await service.get_cost_summary(session, project_id)


@router.get("/{project_id}/budget", response_model=ProjectBudget | None)
async def get_project_budget(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectBudget | None:
	"""Get budget for a project."""
	return await service.get_budget(session, project_id)


@router.post(
	"/{project_id}/budget",
	response_model=ProjectBudget,
	status_code=status.HTTP_201_CREATED,
)
async def create_project_budget(
	project_id: str,
	data: ProjectBudgetCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectBudget:
	"""Create a budget for a project."""
	return await service.create_budget(session, project_id, data)


@router.patch("/{project_id}/budget/{budget_id}", response_model=ProjectBudget)
async def update_project_budget(
	project_id: str,
	budget_id: str,
	data: ProjectBudgetUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectBudget:
	"""Update a project budget."""
	budget = await service.update_budget(session, budget_id, data, user.id if data.is_approved else None)
	if not budget:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget not found")
	return budget


# =====================================================
# SLA Endpoints
# =====================================================


@router.get("/{project_id}/slas", response_model=list[SLA])
async def list_project_slas(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[SLA]:
	"""List SLAs for a project."""
	slas = await service.get_project_slas(session, project_id)
	return list(slas)


@router.post(
	"/{project_id}/slas",
	response_model=SLA,
	status_code=status.HTTP_201_CREATED,
)
async def create_sla(
	project_id: str,
	data: SLACreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> SLA:
	"""Create a new SLA."""
	return await service.create_sla(session, project_id, data)


@router.patch("/{project_id}/slas/{sla_id}", response_model=SLA)
async def update_sla(
	project_id: str,
	sla_id: str,
	data: SLAUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> SLA:
	"""Update an SLA."""
	sla = await service.update_sla(session, sla_id, data)
	if not sla:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SLA not found")
	return sla


@router.post("/{project_id}/slas/{sla_id}/check", response_model=SLA)
async def check_sla_status(
	project_id: str,
	sla_id: str,
	current_value: float,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> SLA:
	"""Check and update SLA status."""
	sla = await service.check_sla_status(session, sla_id, current_value)
	if not sla:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SLA not found")
	return sla


@router.get("/{project_id}/sla-alerts", response_model=list[SLAAlert])
async def list_sla_alerts(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	unacknowledged_only: bool = Query(False),
) -> list[SLAAlert]:
	"""List SLA alerts for a project."""
	alerts = await service.get_sla_alerts(session, project_id=project_id, unacknowledged_only=unacknowledged_only)
	return list(alerts)


@router.post("/{project_id}/sla-alerts/{alert_id}/acknowledge", response_model=SLAAlert)
async def acknowledge_sla_alert(
	project_id: str,
	alert_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	resolution_notes: str | None = None,
) -> SLAAlert:
	"""Acknowledge an SLA alert."""
	alert = await service.acknowledge_sla_alert(session, alert_id, user.id, resolution_notes)
	if not alert:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
	return alert


# =====================================================
# Equipment Maintenance Endpoints
# =====================================================


@router.get("/maintenance", response_model=list[EquipmentMaintenance])
async def list_maintenance(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	resource_id: str | None = None,
	status: MaintenanceStatus | None = None,
	upcoming_days: int | None = None,
) -> list[EquipmentMaintenance]:
	"""List maintenance schedules."""
	maintenance = await service.get_maintenance_schedule(session, resource_id, status, upcoming_days)
	return list(maintenance)


@router.post(
	"/maintenance",
	response_model=EquipmentMaintenance,
	status_code=status.HTTP_201_CREATED,
)
async def schedule_maintenance(
	data: EquipmentMaintenanceCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> EquipmentMaintenance:
	"""Schedule equipment maintenance."""
	return await service.schedule_maintenance(session, data)


@router.patch("/maintenance/{maintenance_id}", response_model=EquipmentMaintenance)
async def update_maintenance(
	maintenance_id: str,
	data: EquipmentMaintenanceUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> EquipmentMaintenance:
	"""Update maintenance record."""
	maintenance = await service.update_maintenance(session, maintenance_id, data)
	if not maintenance:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maintenance record not found")
	return maintenance


# =====================================================
# Operator Certification Endpoints
# =====================================================


@router.get("/certifications", response_model=list[OperatorCertification])
async def list_certifications(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	operator_id: str | None = None,
	certification_type: str | None = None,
	active_only: bool = Query(True),
) -> list[OperatorCertification]:
	"""List operator certifications."""
	certs = await service.get_operator_certifications(
		session, operator_id, certification_type, active_only
	)
	return list(certs)


@router.post(
	"/certifications",
	response_model=OperatorCertification,
	status_code=status.HTTP_201_CREATED,
)
async def create_certification(
	data: OperatorCertificationCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> OperatorCertification:
	"""Create an operator certification."""
	return await service.create_certification(session, data)


@router.patch("/certifications/{certification_id}", response_model=OperatorCertification)
async def update_certification(
	certification_id: str,
	data: OperatorCertificationUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> OperatorCertification:
	"""Update an operator certification."""
	cert = await service.update_certification(session, certification_id, data)
	if not cert:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Certification not found")
	return cert


@router.get("/certifications/expiring", response_model=list[OperatorCertification])
async def list_expiring_certifications(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	days: int = Query(30, ge=1, le=365),
) -> list[OperatorCertification]:
	"""List certifications expiring within specified days."""
	certs = await service.get_expiring_certifications(session, days)
	return list(certs)


# =====================================================
# Capacity Planning Endpoints
# =====================================================


@router.get("/{project_id}/capacity-plans", response_model=list[CapacityPlan])
async def list_capacity_plans(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[CapacityPlan]:
	"""List capacity plans for a project."""
	plans = await service.get_capacity_plans(session, project_id)
	return list(plans)


@router.post(
	"/{project_id}/capacity-plans",
	response_model=CapacityPlan,
	status_code=status.HTTP_201_CREATED,
)
async def create_capacity_plan(
	project_id: str,
	data: CapacityPlanCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> CapacityPlan:
	"""Create a capacity plan for a project."""
	return await service.create_capacity_plan(session, project_id, data, user.id)


# =====================================================
# Document Type Distribution Endpoints
# =====================================================


@router.get("/{project_id}/document-types", response_model=list[DocumentTypeDistribution])
async def list_document_type_distributions(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[DocumentTypeDistribution]:
	"""List document type distributions for a project."""
	dists = await service.get_document_type_distributions(session, project_id)
	return list(dists)


@router.post(
	"/{project_id}/document-types",
	response_model=DocumentTypeDistribution,
	status_code=status.HTTP_201_CREATED,
)
async def create_document_type_distribution(
	project_id: str,
	data: DocumentTypeDistributionCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> DocumentTypeDistribution:
	"""Create a document type distribution entry."""
	return await service.create_document_type_distribution(session, project_id, data)


@router.patch("/{project_id}/document-types/{distribution_id}", response_model=DocumentTypeDistribution)
async def update_document_type_distribution(
	project_id: str,
	distribution_id: str,
	data: DocumentTypeDistributionUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> DocumentTypeDistribution:
	"""Update a document type distribution entry."""
	dist = await service.update_document_type_distribution(session, distribution_id, data)
	if not dist:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Distribution not found")
	return dist


# =====================================================
# Priority Queue Endpoints
# =====================================================


@router.get("/{project_id}/priority-queue", response_model=list[BatchPriority])
async def get_priority_queue(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	rush_only: bool = Query(False),
) -> list[BatchPriority]:
	"""Get priority queue for batches in a project."""
	queue = await service.get_priority_queue(session, project_id, rush_only)
	return list(queue)


@router.post(
	"/batch-priority",
	response_model=BatchPriority,
	status_code=status.HTTP_201_CREATED,
)
async def set_batch_priority(
	data: BatchPriorityCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> BatchPriority:
	"""Set priority for a batch."""
	return await service.set_batch_priority(session, data)


@router.patch("/batch-priority/{priority_id}", response_model=BatchPriority)
async def update_batch_priority(
	priority_id: str,
	data: BatchPriorityUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> BatchPriority:
	"""Update batch priority."""
	priority = await service.update_batch_priority(session, priority_id, data)
	if not priority:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Priority entry not found")
	return priority


# =====================================================
# Contract Endpoints
# =====================================================


@router.get("/{project_id}/contracts", response_model=list[ProjectContract])
async def list_project_contracts(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[ProjectContract]:
	"""List contracts for a project."""
	contracts = await service.get_project_contracts(session, project_id)
	return list(contracts)


@router.post(
	"/{project_id}/contracts",
	response_model=ProjectContract,
	status_code=status.HTTP_201_CREATED,
)
async def create_contract(
	project_id: str,
	data: ProjectContractCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectContract:
	"""Create a project contract."""
	return await service.create_contract(session, project_id, data)


@router.patch("/{project_id}/contracts/{contract_id}", response_model=ProjectContract)
async def update_contract(
	project_id: str,
	contract_id: str,
	data: ProjectContractUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectContract:
	"""Update a project contract."""
	contract = await service.update_contract(session, contract_id, data)
	if not contract:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found")
	return contract


# =====================================================
# Workload Forecast Endpoints
# =====================================================


@router.get("/{project_id}/workload-forecasts", response_model=list[WorkloadForecast])
async def list_workload_forecasts(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[WorkloadForecast]:
	"""List workload forecasts for a project."""
	forecasts = await service.get_workload_forecasts(session, project_id)
	return list(forecasts)


@router.post(
	"/{project_id}/workload-forecasts",
	response_model=WorkloadForecast,
	status_code=status.HTTP_201_CREATED,
)
async def create_workload_forecast(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	forecast_period_start: date = Query(...),
	forecast_period_end: date = Query(...),
) -> WorkloadForecast:
	"""Create a workload forecast."""
	from datetime import datetime
	return await service.create_workload_forecast(
		session,
		project_id,
		datetime.combine(forecast_period_start, datetime.min.time()),
		datetime.combine(forecast_period_end, datetime.max.time()),
	)


# =====================================================
# Checkpoint Endpoints
# =====================================================


@router.get("/{project_id}/checkpoints", response_model=list[ProjectCheckpoint])
async def list_project_checkpoints(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[ProjectCheckpoint]:
	"""List checkpoints for a project."""
	checkpoints = await service.get_project_checkpoints(session, project_id)
	return list(checkpoints)


@router.post(
	"/{project_id}/checkpoints",
	response_model=ProjectCheckpoint,
	status_code=status.HTTP_201_CREATED,
)
async def create_checkpoint(
	project_id: str,
	data: ProjectCheckpointCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectCheckpoint:
	"""Create a project checkpoint."""
	return await service.create_checkpoint(session, project_id, data)


@router.patch("/{project_id}/checkpoints/{checkpoint_id}", response_model=ProjectCheckpoint)
async def update_checkpoint(
	project_id: str,
	checkpoint_id: str,
	data: ProjectCheckpointUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectCheckpoint:
	"""Update a checkpoint."""
	checkpoint = await service.update_checkpoint(
		session, checkpoint_id, data, user.id, user.username
	)
	if not checkpoint:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Checkpoint not found")
	return checkpoint


# =====================================================
# Bulk Operations Endpoints
# =====================================================


@router.post(
	"/{project_id}/batches/bulk-import",
	response_model=BulkOperationResult,
)
async def bulk_import_batches(
	project_id: str,
	data: BulkBatchImport,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> BulkOperationResult:
	"""Bulk import batches for a project."""
	return await service.bulk_import_batches(session, project_id, data)


@router.post(
	"/batches/bulk-update",
	response_model=BulkOperationResult,
)
async def bulk_update_batches(
	data: BulkBatchUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> BulkOperationResult:
	"""Bulk update batches."""
	return await service.bulk_update_batches(session, data)


# =====================================================
# Dashboard and Analytics Endpoints
# =====================================================


@router.get("/{project_id}/dashboard", response_model=ProjectDashboard)
async def get_project_dashboard(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectDashboard:
	"""Get comprehensive project dashboard data."""
	return await service.get_project_dashboard(session, project_id)


@router.get("/{project_id}/burndown", response_model=BurndownChart)
async def get_burndown_chart(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> BurndownChart:
	"""Get burndown chart data for a project."""
	return await service.get_burndown_chart(session, project_id)


@router.get("/{project_id}/velocity", response_model=VelocityChart)
async def get_velocity_chart(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	period_days: int = Query(30, ge=7, le=365),
) -> VelocityChart:
	"""Get velocity chart data for a project."""
	return await service.get_velocity_chart(session, project_id, period_days)


@router.get("/{project_id}/location-dashboard", response_model=MultiLocationDashboard)
async def get_multi_location_dashboard(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> MultiLocationDashboard:
	"""Get multi-location dashboard for a project."""
	return await service.get_multi_location_dashboard(session, project_id, user.tenant_id)
