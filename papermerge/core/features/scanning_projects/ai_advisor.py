# (c) Copyright Datacraft, 2026
"""AI-powered project advisor using Azure OpenAI or Ollama."""
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.llm import get_llm_client, LLMConfig

from .models import (
	ScanningProjectModel,
	ScanningBatchModel,
	ScanningMilestoneModel,
	QualityControlSampleModel,
	ScanningResourceModel,
	ScanningSesssionModel,
	DailyProjectMetricsModel,
	ProjectIssueModel,
)
from .views import (
	ScanningProjectStatus,
	ScanningBatchStatus,
	QCReviewStatus,
	MilestoneStatus,
	ResourceStatus,
	RiskLevel,
	RecommendationType,
	AIRecommendation,
	ProjectRiskAssessment,
	ScheduleForecast,
	ResourceOptimization,
	AIAdvisorResponse,
)

logger = logging.getLogger(__name__)


def _log_advisor_action(action: str, project_id: str) -> str:
	return f"AI Advisor {action} for project {project_id[:8]}..."


ADVISOR_SYSTEM_PROMPT = """You are an expert project manager specializing in large-scale document digitization and scanning projects. You analyze project metrics, identify risks, and provide actionable recommendations.

Your analysis should be:
1. Data-driven - base conclusions on metrics provided
2. Actionable - provide specific recommendations
3. Risk-aware - identify potential problems early
4. Resource-conscious - optimize operator and scanner utilization

Always provide your response as valid JSON matching the expected schema."""


class ProjectAIAdvisor:
	"""AI-powered advisor for scanning project management."""

	def __init__(self, config: LLMConfig | None = None):
		self.client = get_llm_client(config)

	async def _collect_project_data(
		self,
		session: AsyncSession,
		project_id: str,
	) -> dict[str, Any]:
		"""Collect comprehensive project data for AI analysis."""
		# Get project
		project_stmt = select(ScanningProjectModel).where(
			ScanningProjectModel.id == project_id
		)
		project_result = await session.execute(project_stmt)
		project = project_result.scalar_one_or_none()
		if not project:
			raise ValueError(f"Project not found: {project_id}")

		# Get batch statistics
		batch_stmt = select(
			func.count(ScanningBatchModel.id).label("total"),
			func.sum(func.case((ScanningBatchModel.status == ScanningBatchStatus.COMPLETED, 1), else_=0)).label("completed"),
			func.sum(func.case((ScanningBatchModel.status == ScanningBatchStatus.PENDING, 1), else_=0)).label("pending"),
			func.sum(func.case((ScanningBatchModel.status == ScanningBatchStatus.SCANNING, 1), else_=0)).label("scanning"),
			func.sum(ScanningBatchModel.estimated_pages).label("estimated_pages"),
			func.sum(ScanningBatchModel.actual_pages).label("actual_pages"),
		).where(ScanningBatchModel.project_id == project_id)
		batch_result = await session.execute(batch_stmt)
		batch_stats = batch_result.one()

		# Get milestone status
		milestone_stmt = select(ScanningMilestoneModel).where(
			ScanningMilestoneModel.project_id == project_id
		).order_by(ScanningMilestoneModel.target_date)
		milestone_result = await session.execute(milestone_stmt)
		milestones = [
			{
				"name": m.name,
				"target_date": m.target_date.isoformat() if m.target_date else None,
				"target_pages": m.target_pages,
				"actual_pages": m.actual_pages,
				"status": m.status.value,
			}
			for m in milestone_result.scalars().all()
		]

		# Get QC statistics
		batch_ids_stmt = select(ScanningBatchModel.id).where(
			ScanningBatchModel.project_id == project_id
		)
		batch_ids_result = await session.execute(batch_ids_stmt)
		batch_ids = [r for r in batch_ids_result.scalars().all()]

		qc_stats = {"total": 0, "passed": 0, "failed": 0, "avg_quality": 0.0}
		if batch_ids:
			qc_stmt = select(
				func.count(QualityControlSampleModel.id).label("total"),
				func.sum(func.case((QualityControlSampleModel.review_status == QCReviewStatus.PASSED, 1), else_=0)).label("passed"),
				func.sum(func.case((QualityControlSampleModel.review_status == QCReviewStatus.FAILED, 1), else_=0)).label("failed"),
				func.avg(QualityControlSampleModel.image_quality).label("avg_quality"),
			).where(
				and_(
					QualityControlSampleModel.batch_id.in_(batch_ids),
					QualityControlSampleModel.review_status != QCReviewStatus.PENDING,
				)
			)
			qc_result = await session.execute(qc_stmt)
			qc_row = qc_result.one()
			qc_stats = {
				"total": qc_row.total or 0,
				"passed": qc_row.passed or 0,
				"failed": qc_row.failed or 0,
				"avg_quality": float(qc_row.avg_quality or 0),
			}

		# Get recent daily metrics
		metrics_stmt = select(DailyProjectMetricsModel).where(
			DailyProjectMetricsModel.project_id == project_id
		).order_by(DailyProjectMetricsModel.metric_date.desc()).limit(14)
		metrics_result = await session.execute(metrics_stmt)
		daily_metrics = [
			{
				"date": m.metric_date.isoformat(),
				"pages_scanned": m.pages_scanned,
				"pages_verified": m.pages_verified,
				"pages_rejected": m.pages_rejected,
				"operator_count": m.operator_count,
				"issues_found": m.issues_found,
			}
			for m in metrics_result.scalars().all()
		]

		# Get active sessions
		one_hour_ago = datetime.utcnow() - timedelta(hours=1)
		session_stmt = select(func.count(ScanningSesssionModel.id)).where(
			and_(
				ScanningSesssionModel.project_id == project_id,
				ScanningSesssionModel.ended_at.is_(None),
			)
		)
		session_result = await session.execute(session_stmt)
		active_sessions = session_result.scalar() or 0

		# Get open issues
		issue_stmt = select(ProjectIssueModel).where(
			and_(
				ProjectIssueModel.project_id == project_id,
				ProjectIssueModel.status.in_(["open", "in_progress"]),
			)
		)
		issue_result = await session.execute(issue_stmt)
		open_issues = [
			{
				"title": i.title,
				"type": i.issue_type,
				"severity": i.severity,
				"status": i.status,
				"created_at": i.created_at.isoformat(),
			}
			for i in issue_result.scalars().all()
		]

		# Calculate days remaining
		days_elapsed = 0
		days_remaining = None
		if project.start_date:
			days_elapsed = (datetime.utcnow() - project.start_date).days
		if project.target_end_date:
			days_remaining = (project.target_end_date - datetime.utcnow()).days

		return {
			"project": {
				"id": project.id,
				"name": project.name,
				"status": project.status.value,
				"total_estimated_pages": project.total_estimated_pages,
				"scanned_pages": project.scanned_pages,
				"verified_pages": project.verified_pages,
				"rejected_pages": project.rejected_pages,
				"start_date": project.start_date.isoformat() if project.start_date else None,
				"target_end_date": project.target_end_date.isoformat() if project.target_end_date else None,
				"days_elapsed": days_elapsed,
				"days_remaining": days_remaining,
				"completion_percentage": (project.scanned_pages / project.total_estimated_pages * 100) if project.total_estimated_pages > 0 else 0,
			},
			"batches": {
				"total": batch_stats.total or 0,
				"completed": batch_stats.completed or 0,
				"pending": batch_stats.pending or 0,
				"scanning": batch_stats.scanning or 0,
				"estimated_pages": batch_stats.estimated_pages or 0,
				"actual_pages": batch_stats.actual_pages or 0,
			},
			"milestones": milestones,
			"qc_stats": qc_stats,
			"daily_metrics": daily_metrics,
			"active_sessions": active_sessions,
			"open_issues": open_issues,
		}

	async def analyze_project(
		self,
		session: AsyncSession,
		project_id: str,
	) -> AIAdvisorResponse:
		"""Perform comprehensive AI analysis of a scanning project."""
		logger.info(_log_advisor_action("analyzing", project_id))

		# Collect all project data
		data = await self._collect_project_data(session, project_id)

		# Get project model for dates
		project_data = data["project"]
		target_date = datetime.fromisoformat(project_data["target_end_date"]) if project_data["target_end_date"] else datetime.utcnow() + timedelta(days=30)

		# Build the analysis prompt
		prompt = f"""Analyze this scanning project and provide insights:

PROJECT DATA:
{json.dumps(data, indent=2)}

Provide your analysis as JSON with this exact structure:
{{
  "risk_assessment": {{
    "overall_risk_level": "low|medium|high|critical",
    "schedule_risk": "low|medium|high|critical",
    "quality_risk": "low|medium|high|critical",
    "resource_risk": "low|medium|high|critical",
    "risk_factors": ["list of identified risk factors"],
    "mitigation_suggestions": ["list of mitigation strategies"],
    "confidence_score": 0.0-1.0
  }},
  "schedule_forecast": {{
    "predicted_completion_days_from_target": integer (negative=ahead, positive=behind),
    "on_track": boolean,
    "bottlenecks": ["list of bottlenecks"],
    "recommendations": ["list of schedule recommendations"],
    "confidence_score": 0.0-1.0
  }},
  "resource_optimization": {{
    "current_efficiency": 0.0-1.0,
    "optimal_operator_count": integer,
    "optimal_scanner_count": integer,
    "suggested_schedule_changes": ["list of scheduling suggestions"],
    "underutilized_resources": ["list of underutilized resources"],
    "overloaded_resources": ["list of overloaded resources"],
    "estimated_efficiency_gain": 0.0-1.0
  }},
  "recommendations": [
    {{
      "type": "resource_allocation|scheduling|quality_improvement|risk_mitigation|efficiency",
      "title": "short title",
      "description": "detailed description",
      "priority": 1-10,
      "risk_level": "low|medium|high|critical",
      "estimated_impact": "description of expected impact",
      "action_items": ["specific action items"]
    }}
  ],
  "summary": "2-3 sentence executive summary of the project status and key insights"
}}"""

		# Get AI analysis
		try:
			analysis = await self.client.complete_json(
				prompt=prompt,
				system_prompt=ADVISOR_SYSTEM_PROMPT,
			)
		except Exception as e:
			logger.error(f"AI analysis failed: {e}")
			# Return a basic analysis if AI fails
			return self._fallback_analysis(project_id, data, target_date)

		# Parse and validate the response
		now = datetime.utcnow()
		risk = analysis.get("risk_assessment", {})
		schedule = analysis.get("schedule_forecast", {})
		resource = analysis.get("resource_optimization", {})

		# Calculate predicted completion date
		days_offset = schedule.get("predicted_completion_days_from_target", 0)
		predicted_completion = target_date + timedelta(days=days_offset)

		risk_assessment = ProjectRiskAssessment(
			project_id=project_id,
			overall_risk_level=RiskLevel(risk.get("overall_risk_level", "medium")),
			schedule_risk=RiskLevel(risk.get("schedule_risk", "medium")),
			quality_risk=RiskLevel(risk.get("quality_risk", "low")),
			resource_risk=RiskLevel(risk.get("resource_risk", "low")),
			risk_factors=risk.get("risk_factors", []),
			mitigation_suggestions=risk.get("mitigation_suggestions", []),
			confidence_score=risk.get("confidence_score", 0.7),
			assessed_at=now,
		)

		schedule_forecast = ScheduleForecast(
			project_id=project_id,
			target_date=target_date,
			predicted_completion_date=predicted_completion,
			on_track=schedule.get("on_track", True),
			days_ahead_or_behind=days_offset,
			confidence_score=schedule.get("confidence_score", 0.7),
			bottlenecks=schedule.get("bottlenecks", []),
			recommendations=schedule.get("recommendations", []),
			forecasted_at=now,
		)

		resource_optimization = ResourceOptimization(
			project_id=project_id,
			current_efficiency=resource.get("current_efficiency", 0.7),
			optimal_operator_count=resource.get("optimal_operator_count", 3),
			optimal_scanner_count=resource.get("optimal_scanner_count", 2),
			suggested_schedule_changes=resource.get("suggested_schedule_changes", []),
			underutilized_resources=resource.get("underutilized_resources", []),
			overloaded_resources=resource.get("overloaded_resources", []),
			estimated_efficiency_gain=resource.get("estimated_efficiency_gain", 0.1),
			analyzed_at=now,
		)

		recommendations = []
		for rec in analysis.get("recommendations", []):
			try:
				recommendations.append(AIRecommendation(
					type=RecommendationType(rec.get("type", "efficiency")),
					title=rec.get("title", "Recommendation"),
					description=rec.get("description", ""),
					priority=rec.get("priority", 5),
					risk_level=RiskLevel(rec.get("risk_level", "low")),
					estimated_impact=rec.get("estimated_impact"),
					action_items=rec.get("action_items", []),
					created_at=now,
				))
			except (ValueError, KeyError) as e:
				logger.warning(f"Invalid recommendation: {e}")

		return AIAdvisorResponse(
			project_id=project_id,
			risk_assessment=risk_assessment,
			schedule_forecast=schedule_forecast,
			resource_optimization=resource_optimization,
			recommendations=recommendations,
			summary=analysis.get("summary", "Analysis complete."),
			generated_at=now,
		)

	def _fallback_analysis(
		self,
		project_id: str,
		data: dict[str, Any],
		target_date: datetime,
	) -> AIAdvisorResponse:
		"""Generate a basic analysis when AI is unavailable."""
		now = datetime.utcnow()
		project = data["project"]

		# Simple rule-based risk assessment
		completion_pct = project["completion_percentage"]
		days_remaining = project["days_remaining"] or 30

		# Calculate simple risk levels
		if days_remaining <= 0 and completion_pct < 100:
			schedule_risk = RiskLevel.CRITICAL
		elif completion_pct / max(1, (100 - days_remaining)) < 0.8:
			schedule_risk = RiskLevel.HIGH
		elif completion_pct / max(1, (100 - days_remaining)) < 1.0:
			schedule_risk = RiskLevel.MEDIUM
		else:
			schedule_risk = RiskLevel.LOW

		qc_pass_rate = data["qc_stats"]["passed"] / max(1, data["qc_stats"]["total"])
		if qc_pass_rate < 0.7:
			quality_risk = RiskLevel.HIGH
		elif qc_pass_rate < 0.9:
			quality_risk = RiskLevel.MEDIUM
		else:
			quality_risk = RiskLevel.LOW

		return AIAdvisorResponse(
			project_id=project_id,
			risk_assessment=ProjectRiskAssessment(
				project_id=project_id,
				overall_risk_level=schedule_risk,
				schedule_risk=schedule_risk,
				quality_risk=quality_risk,
				resource_risk=RiskLevel.LOW,
				risk_factors=["AI analysis unavailable - using rule-based assessment"],
				mitigation_suggestions=["Enable AI advisor for comprehensive analysis"],
				confidence_score=0.5,
				assessed_at=now,
			),
			schedule_forecast=ScheduleForecast(
				project_id=project_id,
				target_date=target_date,
				predicted_completion_date=target_date,
				on_track=schedule_risk in (RiskLevel.LOW, RiskLevel.MEDIUM),
				days_ahead_or_behind=0,
				confidence_score=0.5,
				bottlenecks=[],
				recommendations=["Enable AI advisor for detailed forecasting"],
				forecasted_at=now,
			),
			resource_optimization=ResourceOptimization(
				project_id=project_id,
				current_efficiency=0.7,
				optimal_operator_count=3,
				optimal_scanner_count=2,
				suggested_schedule_changes=[],
				underutilized_resources=[],
				overloaded_resources=[],
				estimated_efficiency_gain=0.0,
				analyzed_at=now,
			),
			recommendations=[
				AIRecommendation(
					type=RecommendationType.EFFICIENCY,
					title="Enable AI Analysis",
					description="Configure LLM provider for comprehensive project insights",
					priority=7,
					risk_level=RiskLevel.LOW,
					action_items=["Set LLM_PROVIDER environment variable", "Configure API credentials"],
				)
			],
			summary=f"Project is {completion_pct:.1f}% complete with {days_remaining} days remaining. Basic rule-based analysis performed.",
			generated_at=now,
		)


# Singleton instance
_advisor: ProjectAIAdvisor | None = None


def get_project_advisor(config: LLMConfig | None = None) -> ProjectAIAdvisor:
	"""Get or create the project AI advisor."""
	global _advisor
	if _advisor is None:
		_advisor = ProjectAIAdvisor(config)
	return _advisor
