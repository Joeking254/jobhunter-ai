from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "jobhunter_ai",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.worker.tasks"],
)
celery_app.conf.update(
    broker_connection_retry_on_startup=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue="celery",
    task_routes={
        "app.worker.tasks.discover_opportunities": {"queue": "discovery"},
        "app.worker.tasks.scheduled_discovery_tick": {"queue": "discovery"},
        "app.worker.tasks.analyze_opportunities": {"queue": "analysis"},
        "app.worker.tasks.analyze_all_users": {"queue": "analysis"},
        "app.worker.tasks.process_automatic_applications": {"queue": "applications"},
        "app.worker.tasks.retry_notifications": {"queue": "notifications"},
        "app.worker.tasks.check_upcoming_deadlines": {"queue": "notifications"},
        "app.worker.tasks.send_periodic_summaries": {"queue": "notifications"},
        "app.worker.tasks.check_expired_listings": {"queue": "maintenance"},
        "app.worker.tasks.check_application_statuses": {"queue": "maintenance"},
        "app.worker.tasks.update_daily_analytics": {"queue": "maintenance"},
        "app.worker.tasks.scheduled_database_backup": {"queue": "maintenance"},
        "app.worker.tasks.infrastructure_heartbeat": {"queue": "maintenance"},
    },
    beat_schedule={
        "infrastructure-heartbeat": {
            "task": "app.worker.tasks.infrastructure_heartbeat",
            "schedule": 60.0,
        },
        # Runs every 15 minutes and checks BotConfig.search_frequency_minutes (default 360 min = 6 hours)
        "scheduled-discovery-tick": {
            "task": "app.worker.tasks.scheduled_discovery_tick",
            "schedule": 900.0,
        },
        # Explicit 6-hour opportunity discovery schedule (immediately chains analysis)
        "discover-opportunities-6h": {
            "task": "app.worker.tasks.discover_opportunities",
            "schedule": 21600.0,
        },
        "process-automatic-applications": {
            "task": "app.worker.tasks.process_automatic_applications",
            "schedule": 900.0,
        },
        "notification-delivery": {
            "task": "app.worker.tasks.retry_notifications",
            "schedule": 180.0,
        },
        "deadline-checks-daily": {
            "task": "app.worker.tasks.check_upcoming_deadlines",
            "schedule": 86400.0,
        },
        "expired-listing-checks-daily": {
            "task": "app.worker.tasks.check_expired_listings",
            "schedule": 86400.0,
        },
        "application-status-checks-daily": {
            "task": "app.worker.tasks.check_application_statuses",
            "schedule": 86400.0,
        },
        "analytics-updates-daily": {
            "task": "app.worker.tasks.update_daily_analytics",
            "schedule": 86400.0,
        },
        "database-backup-daily": {
            "task": "app.worker.tasks.scheduled_database_backup",
            "schedule": 86400.0,
        },
        "daily-notification-summaries": {
            "task": "app.worker.tasks.send_periodic_summaries",
            "schedule": 86400.0,
            "args": ("daily",),
        },
        "weekly-notification-summaries": {
            "task": "app.worker.tasks.send_periodic_summaries",
            "schedule": 604800.0,
            "args": ("weekly",),
        },
    },
)
