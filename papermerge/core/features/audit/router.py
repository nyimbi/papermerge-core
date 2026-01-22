import logging
import uuid
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Security, Query
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core import utils, schema, dbapi
from papermerge.core.features.auth import get_current_user
from papermerge.core.features.auth import scopes
from papermerge.core.db.engine import get_db
from .schema import AuditLogParams, ActivityTrendResponse, UserActivityResponse, SecurityAlertResponse, ComplianceReportResponse, TopUsersResponse, OperationDistributionResponse
from .analytics import AuditAnalytics

router = APIRouter(
    prefix="/audit-logs",
    tags=["audit-logs"],
)

logger = logging.getLogger(__name__)


@router.get("/", response_model=schema.PaginatedResponse[schema.AuditLog])
@utils.docstring_parameter(scope=scopes.AUDIT_LOG_VIEW)
async def get_audit_logs(
    user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.AUDIT_LOG_VIEW])],
    params: AuditLogParams = Depends(),
    db_session: AsyncSession = Depends(get_db),
) -> schema.PaginatedResponse[schema.AuditLog]:
    """Get paginated audit logs

    Required scope: `{scope}`
    """
    try:
        advanced_filters = params.to_advanced_filters()

        result = await dbapi.get_audit_logs(
            db_session,
            page_size=params.page_size,
            page_number=params.page_number,
            sort_by=params.sort_by,
            sort_direction=params.sort_direction,
            filters=advanced_filters
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid parameters: {str(e)}")
    except Exception as e:
        logger.error(
            f"Error fetching audit logs by the user {user.id}: {e}",
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    return result


@router.get("/{audit_log_id}", response_model=schema.AuditLogDetails)
@utils.docstring_parameter(scope=scopes.AUDIT_LOG_VIEW)
async def get_audit_log(
    audit_log_id: uuid.UUID,
    user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.AUDIT_LOG_VIEW])],
    db_session: AsyncSession = Depends(get_db),
) -> schema.AuditLogDetails:
    """Get audit log entry details

    Required scope: `{scope}`
    """
    try:
        result = await dbapi.get_audit_log(db_session, audit_log_id=audit_log_id)
    except NoResultFound:
        raise HTTPException(status_code=404, detail="Audit log entry not found")
    except Exception as e:
        logger.error(
            f"Error fetching audit log {audit_log_id} for user {user.id}: {e}",
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    return result


# --- Analytics Endpoints ---

@router.get("/analytics/trend", response_model=ActivityTrendResponse)
@utils.docstring_parameter(scope=scopes.AUDIT_LOG_VIEW)
async def get_activity_trend(
    user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.AUDIT_LOG_VIEW])],
    db_session: AsyncSession = Depends(get_db),
    period: str = Query("daily", regex="^(hourly|daily|weekly)$"),
    days: int = Query(30, ge=1, le=365),
    table_filter: str | None = None,
    operation_filter: str | None = None,
) -> ActivityTrendResponse:
    """Get activity trend over time.

    Required scope: `{scope}`
    """
    try:
        analytics = AuditAnalytics(db_session)
        trend = await analytics.get_activity_trend(
            period=period,
            days=days,
            table_filter=table_filter,
            operation_filter=operation_filter,
        )
        return ActivityTrendResponse(
            period=trend.period,
            data=[
                {"timestamp": p.timestamp.isoformat(), "count": p.count, "breakdown": p.breakdown}
                for p in trend.data
            ],
            total=trend.total,
            average=trend.average,
            peak={"timestamp": trend.peak.timestamp.isoformat(), "count": trend.peak.count} if trend.peak else None,
            trend_direction=trend.trend_direction,
        )
    except Exception as e:
        logger.error(f"Error fetching activity trend: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/analytics/users/top", response_model=TopUsersResponse)
@utils.docstring_parameter(scope=scopes.AUDIT_LOG_VIEW)
async def get_top_users(
    user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.AUDIT_LOG_VIEW])],
    db_session: AsyncSession = Depends(get_db),
    limit: int = Query(10, ge=1, le=50),
    days: int = Query(30, ge=1, le=365),
    operation: str | None = None,
) -> TopUsersResponse:
    """Get top active users.

    Required scope: `{scope}`
    """
    try:
        analytics = AuditAnalytics(db_session)
        users = await analytics.get_top_users(limit=limit, days=days, operation=operation)
        return TopUsersResponse(items=users, period_days=days)
    except Exception as e:
        logger.error(f"Error fetching top users: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/analytics/users/{user_id}", response_model=UserActivityResponse)
@utils.docstring_parameter(scope=scopes.AUDIT_LOG_VIEW)
async def get_user_activity(
    user_id: uuid.UUID,
    user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.AUDIT_LOG_VIEW])],
    db_session: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
) -> UserActivityResponse:
    """Get activity summary for a specific user.

    Required scope: `{scope}`
    """
    try:
        analytics = AuditAnalytics(db_session)
        summary = await analytics.get_user_activity_summary(str(user_id), days=days)
        return UserActivityResponse(
            user_id=summary.user_id,
            username=summary.username,
            total_actions=summary.total_actions,
            operations=summary.operations,
            tables_accessed=summary.tables_accessed,
            first_activity=summary.first_activity.isoformat() if summary.first_activity else None,
            last_activity=summary.last_activity.isoformat() if summary.last_activity else None,
            avg_daily_actions=summary.avg_daily_actions,
            unusual_patterns=summary.unusual_patterns,
        )
    except Exception as e:
        logger.error(f"Error fetching user activity: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/analytics/operations", response_model=OperationDistributionResponse)
@utils.docstring_parameter(scope=scopes.AUDIT_LOG_VIEW)
async def get_operation_distribution(
    user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.AUDIT_LOG_VIEW])],
    db_session: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
) -> OperationDistributionResponse:
    """Get distribution of operations.

    Required scope: `{scope}`
    """
    try:
        analytics = AuditAnalytics(db_session)
        distribution = await analytics.get_operation_distribution(days=days)
        return OperationDistributionResponse(operations=distribution, period_days=days)
    except Exception as e:
        logger.error(f"Error fetching operation distribution: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/analytics/security-alerts", response_model=list[SecurityAlertResponse])
@utils.docstring_parameter(scope=scopes.AUDIT_LOG_VIEW)
async def get_security_alerts(
    user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.AUDIT_LOG_VIEW])],
    db_session: AsyncSession = Depends(get_db),
    hours: int = Query(24, ge=1, le=168),
) -> list[SecurityAlertResponse]:
    """Detect security anomalies in recent activity.

    Required scope: `{scope}`
    """
    try:
        analytics = AuditAnalytics(db_session)
        alerts = await analytics.detect_security_anomalies(hours=hours)
        return [
            SecurityAlertResponse(
                alert_type=a.alert_type,
                severity=a.severity,
                timestamp=a.timestamp.isoformat(),
                description=a.description,
                affected_resources=a.affected_resources,
                user_id=a.user_id,
                details=a.details,
            )
            for a in alerts
        ]
    except Exception as e:
        logger.error(f"Error detecting security alerts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/analytics/compliance-report", response_model=ComplianceReportResponse)
@utils.docstring_parameter(scope=scopes.AUDIT_LOG_VIEW)
async def get_compliance_report(
    user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.AUDIT_LOG_VIEW])],
    db_session: AsyncSession = Depends(get_db),
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> ComplianceReportResponse:
    """Generate a compliance audit report.

    Required scope: `{scope}`
    """
    if not end_date:
        end_date = datetime.utcnow()
    if not start_date:
        start_date = end_date - timedelta(days=30)

    try:
        analytics = AuditAnalytics(db_session)
        report = await analytics.generate_compliance_report(start_date, end_date)
        return ComplianceReportResponse(
            report_period_start=report.report_period[0].isoformat(),
            report_period_end=report.report_period[1].isoformat(),
            total_events=report.total_events,
            events_by_operation=report.events_by_operation,
            events_by_table=report.events_by_table,
            users_active=report.users_active,
            security_alerts_count=len(report.security_alerts),
            data_retention_status=report.data_retention_status,
        )
    except Exception as e:
        logger.error(f"Error generating compliance report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
