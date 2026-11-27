from datetime import datetime, timedelta, timezone
import json

import httpx
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base, import_models
from app.models.models import (
    Application,
    ApplicationAttempt,
    BotConfig,
    BotRun,
    Document,
    GeneratedDocument,
    JobMatch,
    JobSource,
    Notification,
    Opportunity,
    User,
)
from app.services.application.automation import BrowserAdapter, FormDetection, FormField
from app.services.application.engine import prepare_application, run_automatic_submissions, submit_application
from app.services.discovery.runner import expire_stale_opportunities
from app.worker.celery_app import celery_app
from app.worker.control import (
    DistributedTaskLock,
    clear_shutdown_flag,
    enforce_source_rate_limit,
    get_or_create_bot_config,
    get_worker_health_and_queues,
    record_worker_heartbeat,
    recover_interrupted_applications,
    request_graceful_shutdown,
    task_lock,
)
from app.worker.tasks import check_pending_application_statuses, execute_tracked_task

import_models()


class FakeRedis:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.store = {}
        self.lists = {}

    def set(self, key, value, nx=False, ex=None):
        if self.fail:
            raise RedisConnectionError("Simulated Redis restart")
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    def get(self, key):
        if self.fail:
            raise RedisConnectionError("Simulated Redis restart")
        return self.store.get(key)

    def eval(self, _script, _numkeys, key, token):
        if self.fail:
            raise RedisConnectionError("Simulated Redis restart")
        if self.store.get(key) == token:
            del self.store[key]
            return 1
        return 0

    def ping(self):
        if self.fail:
            raise RedisConnectionError("Simulated Redis restart")
        return True

    def llen(self, key):
        if self.fail:
            raise RedisConnectionError("Simulated Redis restart")
        return len(self.lists.get(key, []))

    def keys(self, pattern):
        if self.fail:
            raise RedisConnectionError("Simulated Redis restart")
        prefix = pattern.rstrip("*")
        return [k for k in self.store if k.startswith(prefix)]

    def close(self):
        pass


def _make_db(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{tmp_path / 'worker.db'}")
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = User(email="bot@example.com", password_hash="hash", first_name="Bot", last_name="Owner", is_admin=True, is_active=True)
    source = JobSource(
        name="RateLimitedBoard",
        base_url="https://board.example",
        connector_type="rss",
        config_json=json.dumps({"automation_permitted": True, "rate_limit_seconds": 5}),
    )
    db.add_all([user, source])
    db.flush()
    opp = Opportunity(
        source_id=source.id,
        external_id="w-1",
        dedupe_hash="w-1",
        title="Platform Engineer",
        company="OpsCo",
        url="https://board.example/apply",
        description="Python Redis Celery",
        deadline=datetime.now(timezone.utc) + timedelta(days=2),
    )
    db.add(opp)
    db.flush()
    db.add(JobMatch(user_id=user.id, opportunity_id=opp.id, score=92, eligible=True, analysis_json="{}"))
    for kind in ("cv", "cover_letter"):
        doc = Document(user_id=user.id, name=f"{kind}.pdf", document_type=f"generated_{kind}", storage_key=f"{kind}.pdf", extracted_text=kind)
        db.add(doc)
        db.flush()
        db.add(GeneratedDocument(user_id=user.id, opportunity_id=opp.id, document_id=doc.id, document_type=kind, file_format="pdf", template_name="entry_level", version=1, editable_text=kind))
    db.commit()
    return db, user, source, opp


def test_celery_schedules_queues_and_retry_configuration():
    beat = celery_app.conf.beat_schedule
    assert beat["discover-opportunities-6h"]["schedule"] == 21600.0
    assert beat["deadline-checks-daily"]["schedule"] == 86400.0
    assert beat["expired-listing-checks-daily"]["schedule"] == 86400.0
    assert beat["application-status-checks-daily"]["schedule"] == 86400.0
    assert beat["analytics-updates-daily"]["schedule"] == 86400.0
    assert beat["notification-delivery"]["schedule"] <= 300.0
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    routes = celery_app.conf.task_routes
    assert routes["app.worker.tasks.discover_opportunities"]["queue"] == "discovery"
    assert routes["app.worker.tasks.analyze_all_users"]["queue"] == "analysis"
    assert routes["app.worker.tasks.process_automatic_applications"]["queue"] == "applications"
    assert routes["app.worker.tasks.retry_notifications"]["queue"] == "notifications"


def test_worker_failure_logs_alert_and_recovers(tmp_path):
    clear_shutdown_flag()
    db, user, _source, _opp = _make_db(tmp_path)

    def boom():
        raise RuntimeError("Upstream feed HTTP 503")

    with pytest.raises(RuntimeError, match="Upstream feed HTTP 503"):
        execute_tracked_task(db, "discover_opportunities", "discovery", "test_fail", boom, attempt=1)

    failed_run = db.scalar(select(BotRun).where(BotRun.bot_name == "discover_opportunities"))
    assert failed_run is not None
    assert failed_run.status == "failed"
    assert "Upstream feed HTTP 503" in (failed_run.error_message or "")
    alert = db.scalar(select(Notification).where(Notification.user_id == user.id))
    assert alert is not None
    assert "Worker Failure" in alert.title

    # Lock was released on failure so subsequent retry succeeds
    status, res = execute_tracked_task(db, "discover_opportunities", "discovery", "test_fail", lambda: {"created": 2}, attempt=2)
    assert status == "success"
    assert res == {"created": 2}


def test_redis_restart_resilience_for_locks_rate_limits_and_health(tmp_path):
    db, _user, source, _opp = _make_db(tmp_path)
    fake_redis = FakeRedis(fail=True)

    # 1. Health monitoring reports redis unavailable during restart without crashing
    down_health = get_worker_health_and_queues(db, redis_factory=lambda: fake_redis)
    assert down_health["redis_status"] == "unavailable"

    # 2. Task lock falls back cleanly when Redis is down and prevents overlapping lock
    lock1 = DistributedTaskLock("redis-restart-test", redis_factory=lambda: fake_redis)
    lock2 = DistributedTaskLock("redis-restart-test", redis_factory=lambda: fake_redis)
    assert lock1.acquire() is True
    assert lock2.acquire() is False
    lock1.release()

    # 3. Source rate limiting works during Redis outage and after Redis recovers
    sleeps = []
    enforce_source_rate_limit(source, redis_factory=lambda: fake_redis, sleep_fn=sleeps.append)
    enforce_source_rate_limit(source, redis_factory=lambda: fake_redis, sleep_fn=sleeps.append)
    assert len(sleeps) >= 1 and sleeps[-1] > 0

    # 4. Redis comes back online
    fake_redis.fail = False
    assert record_worker_heartbeat("worker-1", redis_factory=lambda: fake_redis) is True
    up_health = get_worker_health_and_queues(db, redis_factory=lambda: fake_redis)
    assert up_health["redis_status"] == "ok"
    assert any(w["worker_id"] == "worker-1" for w in up_health["workers"])


def test_repeated_tasks_and_overlapping_application_prevention(tmp_path):
    clear_shutdown_flag()
    db, user, _source, opp = _make_db(tmp_path)
    app = prepare_application(db, user, opp, {"Email": "bot@example.com"})
    assert app.status == "ready_to_submit"

    # Repeated/overlapping discovery task skipped while lock is held
    with task_lock("dup_task_key") as held:
        assert held is True
        status, _res = execute_tracked_task(db, "discover_opportunities", "discovery", "dup_task_key", lambda: "never")
        assert status == "skipped_duplicate"

    # Overlapping duplicate submission on the same application is blocked
    with task_lock(f"application:{app.id}") as held_app:
        assert held_app is True

        class DummyAdapter(BrowserAdapter):
            def detect_form(self, url):
                raise AssertionError("Should not reach browser when locked")

        with pytest.raises(RuntimeError, match="Duplicate overlapping submission prevented"):
            submit_application(db, app, DummyAdapter())


def test_interrupted_browser_session_and_graceful_shutdown(tmp_path):
    clear_shutdown_flag()
    db, user, _source, opp = _make_db(tmp_path)
    app = prepare_application(db, user, opp, {"Email": "bot@example.com"})
    closed = {"flag": False}

    class InterruptedBrowser(BrowserAdapter):
        def detect_form(self, _url):
            return FormDetection([FormField("email", "Email", required=True)])

        def fill_form(self, _fields, _answers, _cv, _cover):
            raise RuntimeError("Browser session crashed mid-fill")

        def submit(self):
            raise AssertionError("Should not submit after crash")

        def close(self):
            closed["flag"] = True

    adapter = InterruptedBrowser()
    try:
        submit_application(db, app, adapter)
    finally:
        adapter.close()

    assert closed["flag"] is True
    assert app.status == "failed"
    assert "crashed mid-fill" in (app.last_error or "")
    attempt = db.scalar(select(ApplicationAttempt).where(ApplicationAttempt.application_id == app.id))
    assert attempt is not None and attempt.status == "failed"

    # Stranded 'submitting' application is safely recovered on worker startup
    app.status = "submitting"
    db.commit()
    assert recover_interrupted_applications(db) == 1
    db.refresh(app)
    assert app.status == "failed"

    # Graceful shutdown flag skips new tasks cleanly
    request_graceful_shutdown()
    status, _ = execute_tracked_task(db, "discover_opportunities", "discovery", "shutdown-test", lambda: "ran")
    assert status == "skipped_shutdown"
    clear_shutdown_flag()


def test_expired_listings_status_checks_and_bot_controls_api(client, tmp_path):
    reg = client.post("/api/auth/register", json={"email": "ctrl@example.com", "password": "StrongPassword1", "first_name": "Ada", "last_name": "Lovelace"})
    assert reg.status_code == 201
    headers = {"X-CSRF-Token": reg.cookies["jobhunter_csrf"]}

    # Dashboard bot controls: pause, resume, auto-apply pause, frequency & threshold updates
    assert client.post("/api/bot/pause", headers=headers).json()["bot_paused"] is True
    assert client.post("/api/bot/resume", headers=headers).json()["bot_paused"] is False
    assert client.post("/api/bot/auto-apply/pause", headers=headers).json()["auto_apply_paused"] is True
    cfg = client.put("/api/bot/config", headers=headers, json={"search_frequency_minutes": 180, "match_strong_threshold": 88, "match_approval_threshold": 70})
    assert cfg.status_code == 200
    assert cfg.json()["search_frequency_minutes"] == 180
    assert cfg.json()["match_strong_threshold"] == 88

    # Manual search executes and writes BotRun log
    search = client.post("/api/bot/search-now", headers=headers)
    assert search.status_code == 200
    status_res = client.get("/api/bot/status")
    assert status_res.status_code == 200
    assert len(status_res.json()["recent_runs"]) >= 1

    # Expired listing check & confirmation_pending daily status check
    db, user, _source, opp = _make_db(tmp_path / "exp")
    app = Application(user_id=user.id, opportunity_id=opp.id, status="confirmation_pending", application_url="https://board.example/status/1")
    db.add(app)
    db.commit()

    http_client = httpx.Client(transport=httpx.MockTransport(lambda _req: httpx.Response(200, text="Confirmation ID: CONF-888")))
    assert check_pending_application_statuses(db, http_client=http_client) == 1
    db.refresh(app)
    assert app.status == "submitted"
    assert app.confirmation_reference == "CONF-888"

    # Expired deadline expires opportunity & pending applications
    opp.deadline = datetime.now(timezone.utc) - timedelta(hours=1)
    app2_opp = Opportunity(source_id=opp.source_id, external_id="w-2", dedupe_hash="w-2", title="Old Role", company="OpsCo", url="https://board.example/old", deadline=datetime.now(timezone.utc) - timedelta(days=1))
    db.add(app2_opp)
    db.flush()
    app2 = Application(user_id=user.id, opportunity_id=app2_opp.id, status="ready_to_submit", application_url=app2_opp.url)
    db.add(app2)
    db.commit()
    assert expire_stale_opportunities(db) >= 1
    db.refresh(app2)
    assert app2.status == "expired"

    # Paused auto-apply prevents automatic submissions
    cfg_row = get_or_create_bot_config(db)
    cfg_row.auto_apply_paused = True
    db.commit()
    assert run_automatic_submissions(db, lambda _uid: BrowserAdapter()) == []
