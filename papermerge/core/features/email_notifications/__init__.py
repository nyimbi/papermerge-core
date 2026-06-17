# (c) Copyright Datacraft, 2026
"""Email notification system for dArchiva.

Provides:
  - EmailService: SMTP send via env-var config
  - HTML templates: batch_complete, sla_breach, exception_alert, weekly_kpi_summary
  - Celery task: darchiva.notifications.send_email
  - FastAPI router: GET/PUT /notifications/preferences
"""
