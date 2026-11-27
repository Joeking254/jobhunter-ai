from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import time
from typing import Any, Callable

from celery.signals import worker_ready, worker_shutting_down
import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.models import Application, BotRun, JobMatch, Opportunity, User, UserSettings
from app.services.ai.matching import match_opportunity
from app.services.application.automation import PlaywrightBrowserAdapter, extract_confirmation_reference
from app.services.application.engine import run_automatic_submissions
from app.services.discovery.runner import expire_stale_opportunities, run_all_sources
from app.services.notifications.service import (
    notify_application_outcome,
    notify_upcoming_deadlines,
    retry_failed_notifications,
    send_digest_summary,
)
from app.worker.celery_app import celery_app
from app.worker.control import (
    alert_worker_failure,
    clear_shutdown_flag,
    get_or_create_bot_config,
    is_shutting_down,
    record_worker_heartbeat,
    recover_interrupted_applications,
    request_graceful_shutdown,
    task_lock,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


@worker_ready.connect
def _on_worker_ready(**_kwargs: Any) -> None:
    clear_shutdown_flag()
    record_worker_heartbeat()
    try:
        with SessionLocal() as db:
            recovered = recover_interrupted_applications(db)
            if recovered:
                logger.warning("Recovered interrupted applications on worker startup", extra={"count": recovered})
    except Exception:
        logger.exception("Failed to recover interrupted applications on startup")


@worker_shutting_down.connect
def _on_worker_shutting_down(**_kwargs: Any) -> None:
    logger.info("Worker graceful shutdown requested")
    request_graceful_shutdown()


def execute_tracked_task(
    db: Session,
    bot_name: str,
    queue_name: str,
    lock_key: str,
    fn: Callable[[], Any],
    *,
    task_id: str | None = None,
    attempt: int = 1,
    ignore_bot_pause: bool = False,
    lock_ttl: int = 600,
) -> tuple[str, Any]:
    """Run a background task with locking, duplicate prevention, BotRun logging, and failure alerts."""
    if is_shutting_down():
        run = BotRun(bot_name=bot_name, queue_name=queue_name, task_id=task_id, status="skipped_shutdown", attempt=attempt, started_at=_utcnow(), finished_at=_utcnow())
        db.add(run)
        db.commit()
        return "skipped_shutdown", None

    config = get_or_create_bot_config(db)
    if not ignore_bot_pause and config.bot_paused:
        run = BotRun(bot_name=bot_name, queue_name=queue_name, task_id=task_id, status="skipped_paused", attempt=attempt, started_at=_utcnow(), finished_at=_utcnow())
        db.add(run)
        db.commit()
        return "skipped_paused", None

    with task_lock(lock_key, ttl_seconds=lock_ttl) as acquired:
        if not acquired:
            run = BotRun(bot_name=bot_name, queue_name=queue_name, task_id=task_id, status="skipped_duplicate", attempt=attempt, started_at=_utcnow(), finished_at=_utcnow())
            db.add(run)
            db.commit()
            return "skipped_duplicate", None

        started = _utcnow()
        t0 = time.monotonic()
        run = BotRun(bot_name=bot_name, queue_name=queue_name, task_id=task_id, status="running", attempt=attempt, started_at=started)
        db.add(run)
        db.commit()
        try:
            result = fn()
            run.status = "success"
            run.finished_at = _utcnow()
            run.duration_ms = int((time.monotonic() - t0) * 1000)
            run.details_json = json.dumps({"result": result}, default=str)
            db.commit()
            return "success", result
        except Exception as exc:
            run.status = "failed"
            run.finished_at = _utcnow()
            run.duration_ms = int((time.monotonic() - t0) * 1000)
            run.error_message = str(exc)[:2000]
            db.commit()
            alert_worker_failure(db, bot_name, str(exc))
            raise


def _run_analysis_for_all_users(db: Session) -> int:
    users = db.scalars(select(User).where(User.is_active.is_(True))).all()
    opportunities = db.scalars(select(Opportunity).where(Opportunity.expired_at.is_(None))).all()
    for user in users:
        for opportunity in opportunities:
            if is_shutting_down():
                return len(users) * len(opportunities)
            match_opportunity(db, user, opportunity)
    return len(users) * len(opportunities)


@celery_app.task(name="app.worker.tasks.infrastructure_heartbeat", bind=True)
def infrastructure_heartbeat(self) -> str:
    record_worker_heartbeat()
    with SessionLocal() as db:
        execute_tracked_task(
            db,
            "infrastructure_heartbeat",
            "maintenance",
            "heartbeat",
            lambda: "ok",
            task_id=getattr(self.request, "id", None),
            ignore_bot_pause=True,
            lock_ttl=55,
        )
    return "ok"


@celery_app.task(
    name="app.worker.tasks.discover_opportunities",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=3600,
    retry_jitter=True,
    max_retries=5,
)
def discover_opportunities(self, manual: bool = False) -> dict[str, int]:
    with SessionLocal() as db:
        def _work() -> dict[str, int]:
            histories = run_all_sources(db)
            config = get_or_create_bot_config(db)
            config.last_discovery_at = _utcnow()
            db.commit()
            # Immediately trigger / run analysis after discovery
            analyzed = _run_analysis_for_all_users(db)
            return {
                "sources_run": len(histories),
                "created": sum(h.created_count for h in histories),
                "analyzed": analyzed,
            }

        status, result = execute_tracked_task(
            db,
            "discover_opportunities",
            "discovery",
            "discover_opportunities",
            _work,
            task_id=getattr(self.request, "id", None),
            attempt=int(getattr(self.request, "retries", 0)) + 1,
            ignore_bot_pause=manual,
        )
        return result if isinstance(result, dict) else {"status": status}  # type: ignore[return-value]


@celery_app.task(name="app.worker.tasks.scheduled_discovery_tick", bind=True)
def scheduled_discovery_tick(self) -> str:
    with SessionLocal() as db:
        config = get_or_create_bot_config(db)
        if config.bot_paused:
            return "paused"
        if config.last_discovery_at is not None:
            next_due = _as_utc(config.last_discovery_at) + timedelta(minutes=max(15, config.search_frequency_minutes))
            if _utcnow() < next_due:
                return "not_due"
    discover_opportunities.delay()
    return "dispatched"


@celery_app.task(
    name="app.worker.tasks.analyze_opportunities",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=3600,
    retry_jitter=True,
    max_retries=5,
)
def analyze_opportunities(self, user_id: str) -> int:
    with SessionLocal() as db:
        def _work() -> int:
            user = db.get(User, user_id)
            if user is None:
                return 0
            opportunities = db.scalars(select(Opportunity).where(Opportunity.expired_at.is_(None))).all()
            for opportunity in opportunities:
                match_opportunity(db, user, opportunity)
            return len(opportunities)

        _status, result = execute_tracked_task(
            db,
            "analyze_opportunities",
            "analysis",
            f"analyze_user:{user_id}",
            _work,
            task_id=getattr(self.request, "id", None),
            attempt=int(getattr(self.request, "retries", 0)) + 1,
        )
        return int(result or 0)


@celery_app.task(
    name="app.worker.tasks.analyze_all_users",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=3600,
    retry_jitter=True,
    max_retries=5,
)
def analyze_all_users(self) -> int:
    with SessionLocal() as db:
        _status, result = execute_tracked_task(
            db,
            "analyze_all_users",
            "analysis",
            "analyze_all_users",
            lambda: _run_analysis_for_all_users(db),
            task_id=getattr(self.request, "id", None),
            attempt=int(getattr(self.request, "retries", 0)) + 1,
        )
        return int(result or 0)


@celery_app.task(
    name="app.worker.tasks.process_automatic_applications",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=3600,
    retry_jitter=True,
    max_retries=3,
)
def process_automatic_applications(self) -> int:
    with SessionLocal() as db:
        def _work() -> int:
            config = get_or_create_bot_config(db)
            if config.auto_apply_paused:
                return 0
            processed = run_automatic_submissions(
                db,
                lambda user_id: PlaywrightBrowserAdapter(Path(settings.document_storage_dir) / user_id / "audit"),
            )
            return len(processed)

        _status, result = execute_tracked_task(
            db,
            "process_automatic_applications",
            "applications",
            "process_automatic_applications",
            _work,
            task_id=getattr(self.request, "id", None),
            attempt=int(getattr(self.request, "retries", 0)) + 1,
        )
        return int(result or 0)


@celery_app.task(
    name="app.worker.tasks.retry_notifications",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=1800,
    retry_jitter=True,
    max_retries=5,
)
def retry_notifications(self) -> int:
    with SessionLocal() as db:
        _status, result = execute_tracked_task(
            db,
            "retry_notifications",
            "notifications",
            "retry_notifications",
            lambda: len(retry_failed_notifications(db)),
            task_id=getattr(self.request, "id", None),
            attempt=int(getattr(self.request, "retries", 0)) + 1,
            ignore_bot_pause=True,
        )
        return int(result or 0)


@celery_app.task(
    name="app.worker.tasks.check_upcoming_deadlines",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def check_upcoming_deadlines(self) -> int:
    with SessionLocal() as db:
        _status, result = execute_tracked_task(
            db,
            "check_upcoming_deadlines",
            "notifications",
            "check_upcoming_deadlines",
            lambda: notify_upcoming_deadlines(db),
            task_id=getattr(self.request, "id", None),
            attempt=int(getattr(self.request, "retries", 0)) + 1,
        )
        return int(result or 0)


@celery_app.task(
    name="app.worker.tasks.check_expired_listings",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def check_expired_listings(self) -> int:
    with SessionLocal() as db:
        _status, result = execute_tracked_task(
            db,
            "check_expired_listings",
            "maintenance",
            "check_expired_listings",
            lambda: expire_stale_opportunities(db),
            task_id=getattr(self.request, "id", None),
            attempt=int(getattr(self.request, "retries", 0)) + 1,
        )
        return int(result or 0)


def check_pending_application_statuses(db: Session, http_client: httpx.Client | None = None) -> int:
    """Check confirmation_pending applications against supported URLs or expired opportunities."""
    pending = list(db.scalars(select(Application).where(Application.status == "confirmation_pending")))
    updated = 0
    owns_client = http_client is None
    client = http_client or httpx.Client(timeout=5.0, follow_redirects=True)
    try:
        for app in pending:
            opp = db.get(Opportunity, app.opportunity_id)
            if opp and opp.expired_at is not None:
                app.status = "expired"
                updated += 1
                continue
            if app.application_url and app.application_url.startswith(("http://", "https://")):
                try:
                    resp = client.get(app.application_url)
                    if resp.status_code == 404 or resp.status_code == 410:
                        app.status = "expired"
                        updated += 1
                    elif resp.status_code < 400:
                        ref = extract_confirmation_reference(resp.text)
                        if ref:
                            app.status = "submitted"
                            app.confirmation_reference = ref
                            app.submitted_at = _utcnow()
                            user = db.get(User, app.user_id)
                            if user:
                                notify_application_outcome(db, user, app, opp)
                            updated += 1
                except Exception:
                    continue
        if updated:
            db.commit()
    finally:
        if owns_client:
            client.close()
    return updated


@celery_app.task(
    name="app.worker.tasks.check_application_statuses",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def check_application_statuses(self) -> int:
    with SessionLocal() as db:
        _status, result = execute_tracked_task(
            db,
            "check_application_statuses",
            "maintenance",
            "check_application_statuses",
            lambda: check_pending_application_statuses(db),
            task_id=getattr(self.request, "id", None),
            attempt=int(getattr(self.request, "retries", 0)) + 1,
        )
        return int(result or 0)


@celery_app.task(
    name="app.worker.tasks.update_daily_analytics",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def update_daily_analytics(self) -> dict[str, int]:
    with SessionLocal() as db:
        def _work() -> dict[str, int]:
            config = get_or_create_bot_config(db)
            config.last_analytics_at = _utcnow()
            snapshot = {
                "opportunities": int(db.scalar(select(func.count(Opportunity.id))) or 0),
                "matches": int(db.scalar(select(func.count(JobMatch.id))) or 0),
                "submitted": int(db.scalar(select(func.count(Application.id)).where(Application.status == "submitted")) or 0),
            }
            db.commit()
            return snapshot

        _status, result = execute_tracked_task(
            db,
            "update_daily_analytics",
            "maintenance",
            "update_daily_analytics",
            _work,
            task_id=getattr(self.request, "id", None),
            attempt=int(getattr(self.request, "retries", 0)) + 1,
            ignore_bot_pause=True,
        )
        return result if isinstance(result, dict) else {}


@celery_app.task(
    name="app.worker.tasks.send_periodic_summaries",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def send_periodic_summaries(self, period: str = "daily") -> int:
    with SessionLocal() as db:
        def _work() -> int:
            users = db.scalars(select(User).where(User.is_active.is_(True))).all()
            sent = 0
            for user in users:
                user_settings = db.scalar(select(UserSettings).where(UserSettings.user_id == user.id))
                if period == "daily" and user_settings and user_settings.notification_frequency == "weekly":
                    continue
                sent += len(send_digest_summary(db, user, period=period))
            return sent

        _status, result = execute_tracked_task(
            db,
            f"send_periodic_summaries_{period}",
            "notifications",
            f"send_periodic_summaries:{period}",
            _work,
            task_id=getattr(self.request, "id", None),
            attempt=int(getattr(self.request, "retries", 0)) + 1,
        )
        return int(result or 0)


@celery_app.task(
    name="app.worker.tasks.scheduled_database_backup",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def scheduled_database_backup(self) -> str:
    from scripts.backup import backup_database
    with SessionLocal() as db:
        _status, result = execute_tracked_task(
            db,
            "scheduled_database_backup",
            "maintenance",
            "scheduled_database_backup",
            lambda: str(backup_database(Path(settings.backup_dir))),
            task_id=getattr(self.request, "id", None),
            attempt=int(getattr(self.request, "retries", 0)) + 1,
            ignore_bot_pause=True,
        )
        return str(result or "")
