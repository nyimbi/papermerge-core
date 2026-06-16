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
    period: str = Query("daily", pattern="^(hourly|daily|weekly)$"),
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


@router.get("/export")
@utils.docstring_parameter(scope=scopes.AUDIT_LOG_VIEW)
async def export_audit_logs(
    user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.AUDIT_LOG_VIEW])],
    db_session: AsyncSession = Depends(get_db),
    format: str = Query("csv", pattern="^(csv|pdf)$"),
    # Re-use the same filter params as the list endpoint
    filter_operation: str | None = Query(None),
    filter_table_name: str | None = Query(None),
    filter_username: str | None = Query(None),
    filter_user_id: str | None = Query(None),
    filter_record_id: str | None = Query(None),
    filter_timestamp_from: str | None = Query(None),
    filter_timestamp_to: str | None = Query(None),
    filter_free_text: str | None = Query(None),
) -> Response:
    """Export audit logs as CSV or printable HTML (PDF).

    Required scope: `{scope}`

    - **format=csv**: returns a downloadable CSV file
    - **format=pdf**: returns printable HTML with a print stylesheet; open in browser and Print→Save as PDF
    """
    import csv
    import io
    import html as html_mod
    from datetime import timezone
    from fastapi.responses import Response as FastAPIResponse
    from sqlalchemy import select as sa_select, and_, or_, func as sa_func, String as sa_String
    from papermerge.core.features.audit.db import orm as audit_orm

    # ── build query (no pagination, all matching rows) ──────────────────────
    stmt = sa_select(audit_orm.AuditLog).order_by(audit_orm.AuditLog.timestamp.desc())

    conditions = []

    if filter_operation:
        ops = [op.strip().upper() for op in filter_operation.split(",") if op.strip()]
        if ops:
            conditions.append(audit_orm.AuditLog.operation.in_(ops))

    if filter_table_name:
        tables = [t.strip() for t in filter_table_name.split(",") if t.strip()]
        if tables:
            conditions.append(audit_orm.AuditLog.table_name.in_(tables))

    if filter_username:
        usernames = [u.strip() for u in filter_username.split(",") if u.strip()]
        if usernames:
            conditions.append(audit_orm.AuditLog.username.in_(usernames))

    if filter_user_id:
        try:
            uid = uuid.UUID(filter_user_id)
            conditions.append(audit_orm.AuditLog.user_id == uid)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid filter_user_id UUID")

    if filter_record_id:
        try:
            rid = uuid.UUID(filter_record_id)
            conditions.append(audit_orm.AuditLog.record_id == rid)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid filter_record_id UUID")

    if filter_timestamp_from:
        try:
            dt_from = datetime.fromisoformat(filter_timestamp_from.replace("Z", "+00:00"))
            conditions.append(audit_orm.AuditLog.timestamp >= dt_from)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid filter_timestamp_from")

    if filter_timestamp_to:
        try:
            dt_to = datetime.fromisoformat(filter_timestamp_to.replace("Z", "+00:00"))
            conditions.append(audit_orm.AuditLog.timestamp <= dt_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid filter_timestamp_to")

    if filter_free_text:
        conditions.append(
            or_(
                sa_func.cast(audit_orm.AuditLog.record_id, sa_String).ilike(f"%{filter_free_text}%"),
                sa_func.cast(audit_orm.AuditLog.user_id, sa_String).ilike(f"%{filter_free_text}%"),
                audit_orm.AuditLog.username.ilike(f"%{filter_free_text}%"),
                audit_orm.AuditLog.table_name.ilike(f"%{filter_free_text}%"),
                audit_orm.AuditLog.operation.ilike(f"%{filter_free_text}%"),
            )
        )

    if conditions:
        stmt = stmt.where(and_(*conditions))

    result = await db_session.execute(stmt)
    logs = result.scalars().all()

    # ── build filter summary string for headers ──────────────────────────────
    active_filters: list[str] = []
    if filter_operation:
        active_filters.append(f"Operation: {filter_operation}")
    if filter_table_name:
        active_filters.append(f"Table: {filter_table_name}")
    if filter_username:
        active_filters.append(f"User: {filter_username}")
    if filter_timestamp_from:
        active_filters.append(f"From: {filter_timestamp_from}")
    if filter_timestamp_to:
        active_filters.append(f"To: {filter_timestamp_to}")
    filter_summary = ", ".join(active_filters) if active_filters else "None"

    generated_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    file_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── CSV export ────────────────────────────────────────────────────────────
    if format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "timestamp", "user_email", "action", "table_name", "record_id", "changes_summary"
        ])
        for log in logs:
            ts = log.timestamp.isoformat() if log.timestamp else ""
            user_email = log.username or (str(log.user_id) if log.user_id else "")
            action = str(log.operation.value if hasattr(log.operation, "value") else log.operation)
            table = log.table_name or ""
            record = str(log.record_id) if log.record_id else ""
            # Build changes summary from changed_fields / old+new values
            if log.changed_fields:
                summary = "Changed: " + ", ".join(log.changed_fields)
            elif log.audit_message:
                summary = log.audit_message
            elif log.new_values:
                keys = list(log.new_values.keys())[:5]
                summary = "Fields: " + ", ".join(keys)
            else:
                summary = ""
            writer.writerow([ts, user_email, action, table, record, summary])

        filename = f"audit-{file_date}.csv"
        return FastAPIResponse(
            content=buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-cache",
            },
        )

    # ── HTML/print export (PDF) ───────────────────────────────────────────────
    rows_html_parts: list[str] = []
    for log in logs:
        ts = log.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC") if log.timestamp else ""
        user_email = html_mod.escape(log.username or (str(log.user_id) if log.user_id else "—"))
        action = html_mod.escape(
            str(log.operation.value if hasattr(log.operation, "value") else log.operation)
        )
        table = html_mod.escape(log.table_name or "")
        record = html_mod.escape(str(log.record_id) if log.record_id else "")
        if log.changed_fields:
            summary = html_mod.escape("Changed: " + ", ".join(log.changed_fields))
        elif log.audit_message:
            summary = html_mod.escape(log.audit_message)
        elif log.new_values:
            keys = list(log.new_values.keys())[:5]
            summary = html_mod.escape("Fields: " + ", ".join(keys))
        else:
            summary = ""
        rows_html_parts.append(
            f"<tr><td>{ts}</td><td>{user_email}</td><td>{action}</td>"
            f"<td>{table}</td><td>{record}</td><td>{summary}</td></tr>"
        )

    rows_html = "\n".join(rows_html_parts)
    row_count = len(logs)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>dArchiva Audit Log Export</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: Arial, Helvetica, sans-serif; font-size: 12pt; color: #111; background: #fff; padding: 24px; }}
    header {{ border-bottom: 2px solid #1a56db; padding-bottom: 12px; margin-bottom: 16px; }}
    header h1 {{ font-size: 18pt; color: #1a56db; }}
    header .meta {{ font-size: 9pt; color: #555; margin-top: 4px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 9pt; }}
    thead tr {{ background: #1a56db; color: #fff; }}
    thead th {{ padding: 6px 8px; text-align: left; font-weight: bold; }}
    tbody tr:nth-child(even) {{ background: #f3f6fb; }}
    tbody td {{ padding: 5px 8px; border-bottom: 1px solid #dde3ee; word-break: break-word; }}
    .summary {{ font-size: 9pt; color: #444; margin-bottom: 12px; }}
    @media print {{
      body {{ font-size: 10pt; padding: 0; }}
      header {{ padding-bottom: 8px; }}
      thead tr {{ background: #1a56db !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
      tbody tr:nth-child(even) {{ background: #f3f6fb !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
      @page {{ margin: 1.5cm; size: A4 landscape; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>dArchiva &mdash; Audit Log Export</h1>
    <div class="meta">Generated: {generated_date} &nbsp;&bull;&nbsp; Total rows: {row_count}</div>
  </header>
  <div class="summary">
    <strong>Filters applied:</strong> {html_mod.escape(filter_summary)}
  </div>
  <table>
    <thead>
      <tr>
        <th>Timestamp</th>
        <th>User / Email</th>
        <th>Action</th>
        <th>Table</th>
        <th>Record ID</th>
        <th>Changes Summary</th>
      </tr>
    </thead>
    <tbody>
      {rows_html if rows_html else '<tr><td colspan="6" style="text-align:center;color:#888">No records found</td></tr>'}
    </tbody>
  </table>
</body>
</html>"""

    return FastAPIResponse(
        content=html_content,
        media_type="text/html; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
        },
    )
