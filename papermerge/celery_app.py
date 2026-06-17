import os

from celery import Celery
from celery.schedules import crontab

PREFIX = os.environ.get("PM_PREFIX", None)
broker_url = os.environ.get("PM_REDIS_URL", None)

if broker_url:
    app = Celery("papermerge", broker=broker_url)
else:
    app = Celery("papermerge")


app.conf.broker_transport_options = {
    "max_retries": 3,
    "interval_start": 0,
    "interval_step": 0.2,
    "interval_max": 0.2,
}


def prefixed(name: str) -> str:
    if PREFIX:
        return f"{PREFIX}_{name}"

    return name


def s3_queue_name() -> str:
    """
    User can override S3 queue name by setting PM_S3_QUEUE_NAME

    Depending on the scenarios, s3 queue name may look like:

    - s3: there is no prefix and no override
    - demo_s3: there is a prefix
    - s3_demo_node4: user has overridden PM_S3_QUEUE_NAME with
        queue name specific to the k8s node.
    """
    name = os.environ.get("PM_S3_QUEUE_NAME", None)
    if name is not None:
        return name

    return prefixed("s3")


def s3preview_queue_name() -> str:
    """
    User can override S3 preview queue name by setting
    PM_S3_PREVIEW_QUEUE_NAME

    Depending on the scenarios, s3 queue name may look like:

    - s3preview: there is no prefix and no override
    - demo_s3review: there is a prefix
    - s3preview_demo_node4: user has overridden
        PM_S3_PREVIEW_QUEUE_NAME with queue name specific
        to the k8s node.
    """
    name = os.environ.get("PM_S3_PREVIEW_QUEUE_NAME", None)
    if name is not None:
        return name

    return prefixed("s3preview")


app.conf.task_routes = {
    "s3": {"queue": s3_queue_name()},
    "process_upload": {"queue": s3_queue_name()},
    # `s3_worker`: generates previews and uploads them to s3 storage
    # via s3preview queue
    "s3preview": {"queue": s3preview_queue_name()},
    "ocr": {"queue": prefixed("ocr")},
    "path_tmpl": {"queue": prefixed("path_tmpl")},
    "workflow.deadline_monitor": {"queue": prefixed("workflow")},
    "workflow.metrics_collector": {"queue": prefixed("workflow")},
    "workflow.sla_dashboard_refresh": {"queue": prefixed("workflow")},
    # Ingestion and form tasks run on the core worker
    "darchiva.ingestion.start_watcher": {"queue": prefixed("core")},
    "darchiva.ingestion.process_file": {"queue": prefixed("core")},
    "darchiva.ingestion.process_batch": {"queue": prefixed("core")},
    "darchiva.ingestion.process_email": {"queue": prefixed("core")},
    "darchiva.form.process": {"queue": prefixed("core")},
    # Email polling tasks run on the core worker
    "darchiva.email.poll_account": {"queue": prefixed("core")},
    "darchiva.email.poll_all_accounts": {"queue": prefixed("core")},
    # Legacy names from papermerge.core.tasks (sync_email_account etc.)
    "papermerge.core.tasks.sync_email_account": {"queue": prefixed("core")},
    "papermerge.core.tasks.sync_all_email_accounts": {"queue": prefixed("core")},
    "papermerge.core.tasks.process_email_attachments": {"queue": prefixed("core")},
    # Document intelligence tasks (embeddings, NER, re-scan)
    "darchiva.documents.index_embeddings": {"queue": prefixed("core")},
    "darchiva.documents.extract_entities": {"queue": prefixed("core")},
    "darchiva.scanning.rescan_requested": {"queue": prefixed("core")},
    # Quality pipeline
    "darchiva.quality.assess_batch": {"queue": prefixed("core")},
    # Outbound webhooks
    "darchiva.webhooks.deliver": {"queue": prefixed("core")},
    "darchiva.webhooks.deliver_ocr_complete": {"queue": prefixed("core")},
    # Retention policies
    "darchiva.retention.sweep": {"queue": prefixed("core")},
    "darchiva.retention.run_policy": {"queue": prefixed("core")},
    # Document expiry reminders
    "darchiva.expiry.check_reminders": {"queue": prefixed("core")},
    # Bulk export
    "darchiva.export.bulk_export": {"queue": prefixed("core")},
    # Email notifications
    "darchiva.notifications.send_email": {"queue": prefixed("core")},
    # KPI reports
    "darchiva.reports.weekly_kpi": {"queue": prefixed("core")},
    # SFTP polling
    "darchiva.ingestion.poll_sftp_connection": {"queue": prefixed("core")},
    "darchiva.ingestion.poll_all_sftp": {"queue": prefixed("core")},
}

# Celery beat schedule for periodic tasks
app.conf.beat_schedule = {
    "workflow-deadline-monitor": {
        "task": "workflow.deadline_monitor",
        "schedule": 300.0,  # Every 5 minutes
    },
    "workflow-metrics-collector": {
        "task": "workflow.metrics_collector",
        "schedule": 900.0,  # Every 15 minutes
    },
    "workflow-sla-dashboard-refresh": {
        "task": "workflow.sla_dashboard_refresh",
        "schedule": 3600.0,  # Every hour
    },
    "sync-all-email-accounts": {
        "task": "darchiva.email.poll_all_accounts",
        "schedule": 300.0,  # Every 5 minutes — respects per-account sync_interval_minutes
    },
    "retention-policy-sweep": {
        "task": "darchiva.retention.sweep",
        "schedule": 86400.0,  # Daily
    },
    "expiry-reminders": {
        "task": "darchiva.expiry.check_reminders",
        "schedule": 86400.0,  # Daily
    },
    "weekly-kpi-reports": {
        "task": "darchiva.reports.weekly_kpi",
        "schedule": crontab(day_of_week=1, hour=8, minute=0),
    },
    "poll-all-sftp": {
        "task": "darchiva.ingestion.poll_all_sftp",
        "schedule": 300.0,
    },
}
