from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
import secrets
import threading
import time
from typing import Any, Callable, Iterator

from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import Application, ApplicationAttempt, BotConfig, BotRun, JobSource, User
from app.services.notifications.service import dispatch_event

logger = logging.getLogger(__name__)

WORKER_QUEUES = ("celery", "discovery", "analysis", "applications", "notifications", "maintenance")

_SHUTDOWN_EVENT = threading.Event()
_LOCAL_LOCKS_GUARD = threading.Lock()
_LOCAL_LOCKS: dict[str, str] = {}
_LOCAL_RATE_LIMITS: dict[str, float] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def request_graceful_shutdown() -> None:
    _SHUTDOWN_EVENT.set()


def clear_shutdown_flag() -> None:
    _SHUTDOWN_EVENT.clear()


def is_shutting_down() -> bool:
    return _SHUTDOWN_EVENT.is_set()


def get_redis_client(url: str | None = None) -> Redis:
    return Redis.from_url(url or settings.redis_url, socket_connect_timeout=2, socket_timeout=2, decode_responses=True)


def get_or_create_bot_config(db: Session) -> BotConfig:
    config = db.scalar(select(BotConfig).where(BotConfig.scope_key == "global"))
    if config is None:
        config = BotConfig(
            scope_key="global",
            bot_paused=False,
            auto_apply_paused=False,
            search_frequency_minutes=360,
            match_strong_threshold=settings.match_strong_threshold,
            match_approval_threshold=settings.match_approval_threshold,
        )
        db.add(config)
        db.commit()
    return config


def effective_match_thresholds(db: Session) -> tuple[int, int]:
    config = db.scalar(select(BotConfig).where(BotConfig.scope_key == "global"))
    if config is None:
        return settings.match_strong_threshold, settings.match_approval_threshold
    return int(config.match_strong_threshold), int(config.match_approval_threshold)


class DistributedTaskLock:
    """Redis-backed distributed task lock with safe local fallback during Redis restarts."""

    _RELEASE_LUA = (
        "if redis.call('get', KEYS[1]) == ARGV[1] then "
        "return redis.call('del', KEYS[1]) else return 0 end"
    )

    def __init__(
        self,
        key: str,
        ttl_seconds: int = 300,
        redis_factory: Callable[[], Redis] | None = None,
    ):
        self.key = f"jobhunter:lock:{key}"
        self.ttl_seconds = ttl_seconds
        self.token = secrets.token_hex(16)
        self._redis_factory = redis_factory or get_redis_client
        self._acquired_backend: str | None = None

    def acquire(self) -> bool:
        try:
            client = self._redis_factory()
            try:
                ok = bool(client.set(self.key, self.token, nx=True, ex=self.ttl_seconds))
                if ok:
                    self._acquired_backend = "redis"
                return ok
            finally:
                client.close()
        except RedisError as exc:
            logger.warning("Redis lock unavailable; falling back to local lock", extra={"lock_key": self.key, "error": str(exc)})
            with _LOCAL_LOCKS_GUARD:
                if self.key in _LOCAL_LOCKS:
                    return False
                _LOCAL_LOCKS[self.key] = self.token
                self._acquired_backend = "local"
                return True

    def release(self) -> None:
        if self._acquired_backend == "redis":
            try:
                client = self._redis_factory()
                try:
                    client.eval(self._RELEASE_LUA, 1, self.key, self.token)
                finally:
                    client.close()
            except RedisError as exc:
                logger.warning("Redis unavailable while releasing lock", extra={"lock_key": self.key, "error": str(exc)})
        elif self._acquired_backend == "local":
            with _LOCAL_LOCKS_GUARD:
                if _LOCAL_LOCKS.get(self.key) == self.token:
                    _LOCAL_LOCKS.pop(self.key, None)
        self._acquired_backend = None


@contextmanager
def task_lock(
    key: str,
    ttl_seconds: int = 300,
    redis_factory: Callable[[], Redis] | None = None,
) -> Iterator[bool]:
    lock = DistributedTaskLock(key, ttl_seconds=ttl_seconds, redis_factory=redis_factory)
    acquired = lock.acquire()
    try:
        yield acquired
    finally:
        if acquired:
            lock.release()


def source_rate_limit_seconds(source: JobSource) -> float:
    try:
        cfg = json.loads(source.config_json or "{}")
    except json.JSONDecodeError:
        cfg = {}
    value = cfg.get("rate_limit_seconds", cfg.get("min_interval_seconds", settings.discovery_rate_limit_seconds))
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return float(settings.discovery_rate_limit_seconds)


def enforce_source_rate_limit(
    source: JobSource,
    *,
    redis_factory: Callable[[], Redis] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> float:
    """Enforce source-specific minimum interval between requests; returns seconds slept."""
    interval = source_rate_limit_seconds(source)
    if interval <= 0:
        return 0.0
    rate_key = f"jobhunter:ratelimit:source:{source.id}"
    now_ts = time.time()
    slept = 0.0
    try:
        client = (redis_factory or get_redis_client)()
        try:
            last_raw = client.get(rate_key)
            if last_raw is not None:
                elapsed = now_ts - float(last_raw)
                if elapsed < interval:
                    wait_for = interval - elapsed
                    sleep_fn(wait_for)
                    slept = wait_for
            client.set(rate_key, str(time.time()), ex=max(60, int(interval * 10)))
            return slept
        finally:
            client.close()
    except RedisError:
        with _LOCAL_LOCKS_GUARD:
            last_ts = _LOCAL_RATE_LIMITS.get(rate_key)
            if last_ts is not None:
                elapsed = now_ts - last_ts
                if elapsed < interval:
                    wait_for = interval - elapsed
                    sleep_fn(wait_for)
                    slept = wait_for
            _LOCAL_RATE_LIMITS[rate_key] = time.time()
        return slept


def record_worker_heartbeat(
    worker_id: str = "primary",
    queues: tuple[str, ...] = WORKER_QUEUES,
    redis_factory: Callable[[], Redis] | None = None,
) -> bool:
    payload = json.dumps({"worker_id": worker_id, "queues": list(queues), "timestamp": _utcnow().isoformat()})
    try:
        client = (redis_factory or get_redis_client)()
        try:
            client.set(f"jobhunter:worker:heartbeat:{worker_id}", payload, ex=180)
            return True
        finally:
            client.close()
    except RedisError:
        return False


def get_worker_health_and_queues(
    db: Session,
    redis_factory: Callable[[], Redis] | None = None,
) -> dict[str, Any]:
    queue_depths: dict[str, int] = {q: 0 for q in WORKER_QUEUES}
    workers: list[dict[str, Any]] = []
    redis_ok = False
    try:
        client = (redis_factory or get_redis_client)()
        try:
            client.ping()
            redis_ok = True
            for queue_name in WORKER_QUEUES:
                queue_depths[queue_name] = int(client.llen(queue_name) or 0)
            for key in client.keys("jobhunter:worker:heartbeat:*"):
                raw = client.get(key)
                if raw:
                    try:
                        workers.append(json.loads(raw))
                    except json.JSONDecodeError:
                        pass
        finally:
            client.close()
    except RedisError:
        redis_ok = False

    last_heartbeat = db.scalar(
        select(BotRun).where(BotRun.bot_name == "infrastructure_heartbeat").order_by(BotRun.started_at.desc()).limit(1)
    )
    active_runs = list(db.scalars(select(BotRun).where(BotRun.status == "running")))
    return {
        "redis_status": "ok" if redis_ok else "unavailable",
        "shutting_down": is_shutting_down(),
        "workers": workers,
        "last_db_heartbeat_at": last_heartbeat.finished_at if last_heartbeat else None,
        "queue_depths": queue_depths,
        "active_tasks": [{"id": r.id, "bot_name": r.bot_name, "queue_name": r.queue_name, "started_at": r.started_at} for r in active_runs],
    }


def alert_worker_failure(db: Session, task_name: str, error_message: str) -> None:
    recipients = list(db.scalars(select(User).where(User.is_active.is_(True), User.is_admin.is_(True))))
    if not recipients:
        recipients = list(db.scalars(select(User).where(User.is_active.is_(True)).limit(1)))
    for user in recipients:
        try:
            dispatch_event(
                db,
                user,
                "application_failed",
                f"Worker Failure: {task_name}",
                f"Background task '{task_name}' failed.\nError: {error_message[:500]}",
                email_subject=f"JOBHUNTER AI Worker Failure: {task_name}",
                dedupe_key=f"worker_failure:{task_name}:{int(time.time() // 300)}",
                content_hash=error_message[:120],
            )
        except Exception:
            logger.exception("Failed to dispatch worker failure alert", extra={"task_name": task_name})


def recover_interrupted_applications(db: Session) -> int:
    """Reset applications stranded in 'submitting' after an interrupted browser session or worker crash."""
    stuck = list(db.scalars(select(Application).where(Application.status == "submitting")))
    for app in stuck:
        app.status = "failed"
        app.last_error = "Application submission interrupted; session recovered safely"
        attempt = db.scalar(
            select(ApplicationAttempt)
            .where(ApplicationAttempt.application_id == app.id, ApplicationAttempt.status == "started")
            .order_by(ApplicationAttempt.attempt_number.desc())
            .limit(1)
        )
        if attempt is not None:
            attempt.status = "failed"
            attempt.error_message = app.last_error
    if stuck:
        db.commit()
    return len(stuck)
