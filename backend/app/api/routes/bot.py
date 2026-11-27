import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_csrf
from app.models.models import BotConfig, BotRun, Opportunity, User
from app.services.ai.matching import match_opportunity
from app.services.discovery.runner import run_all_sources
from app.worker.control import get_or_create_bot_config, get_worker_health_and_queues

router = APIRouter(prefix="/bot", tags=["autonomous-bot"])


class BotConfigUpdate(BaseModel):
    search_frequency_minutes: int | None = Field(default=None, ge=15, le=10080)
    match_strong_threshold: int | None = Field(default=None, ge=50, le=100)
    match_approval_threshold: int | None = Field(default=None, ge=0, le=99)


def _serialize_config(cfg: BotConfig) -> dict[str, Any]:
    return {
        "bot_paused": cfg.bot_paused,
        "auto_apply_paused": cfg.auto_apply_paused,
        "search_frequency_minutes": cfg.search_frequency_minutes,
        "match_strong_threshold": cfg.match_strong_threshold,
        "match_approval_threshold": cfg.match_approval_threshold,
        "last_discovery_at": cfg.last_discovery_at,
        "last_analytics_at": cfg.last_analytics_at,
    }


@router.get("/status")
def get_bot_status(
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    cfg = get_or_create_bot_config(db)
    health = get_worker_health_and_queues(db)
    recent_runs = [
        {
            "id": r.id,
            "bot_name": r.bot_name,
            "queue_name": r.queue_name,
            "status": r.status,
            "attempt": r.attempt,
            "duration_ms": r.duration_ms,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "error_message": r.error_message,
            "details": json.loads(r.details_json) if r.details_json else None,
        }
        for r in db.scalars(select(BotRun).order_by(BotRun.started_at.desc()).limit(20))
    ]
    return {"config": _serialize_config(cfg), "health": health, "recent_runs": recent_runs}


@router.post("/pause")
def pause_bot(_user: User = Depends(get_current_user), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> dict[str, Any]:
    cfg = get_or_create_bot_config(db)
    cfg.bot_paused = True
    db.commit()
    return _serialize_config(cfg)


@router.post("/resume")
def resume_bot(_user: User = Depends(get_current_user), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> dict[str, Any]:
    cfg = get_or_create_bot_config(db)
    cfg.bot_paused = False
    db.commit()
    return _serialize_config(cfg)


@router.post("/auto-apply/pause")
def pause_auto_apply(_user: User = Depends(get_current_user), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> dict[str, Any]:
    cfg = get_or_create_bot_config(db)
    cfg.auto_apply_paused = True
    db.commit()
    return _serialize_config(cfg)


@router.post("/auto-apply/resume")
def resume_auto_apply(_user: User = Depends(get_current_user), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> dict[str, Any]:
    cfg = get_or_create_bot_config(db)
    cfg.auto_apply_paused = False
    db.commit()
    return _serialize_config(cfg)


@router.put("/config")
def update_bot_config(
    payload: BotConfigUpdate,
    _user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    cfg = get_or_create_bot_config(db)
    strong = payload.match_strong_threshold if payload.match_strong_threshold is not None else cfg.match_strong_threshold
    approval = payload.match_approval_threshold if payload.match_approval_threshold is not None else cfg.match_approval_threshold
    if approval >= strong:
        raise HTTPException(status_code=422, detail="Approval threshold must be lower than strong match threshold")
    if payload.search_frequency_minutes is not None:
        cfg.search_frequency_minutes = payload.search_frequency_minutes
    cfg.match_strong_threshold = strong
    cfg.match_approval_threshold = approval
    db.commit()
    return _serialize_config(cfg)


@router.post("/search-now")
def start_manual_search(
    async_mode: bool = Query(default=False),
    user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if async_mode:
        from app.worker.tasks import discover_opportunities
        task = discover_opportunities.delay(manual=True)
        return {"queued": True, "task_id": task.id}

    from app.worker.tasks import execute_tracked_task
    def _run() -> dict[str, int]:
        histories = run_all_sources(db)
        cfg = get_or_create_bot_config(db)
        from datetime import datetime, timezone
        cfg.last_discovery_at = datetime.now(timezone.utc)
        db.commit()
        matched = 0
        for opp in db.scalars(select(Opportunity).where(Opportunity.expired_at.is_(None))):
            match_opportunity(db, user, opp)
            matched += 1
        return {
            "runs": len(histories),
            "created": sum(h.created_count for h in histories),
            "matched": matched,
        }

    status, result = execute_tracked_task(
        db,
        "manual_search",
        "discovery",
        "discover_opportunities",
        _run,
        ignore_bot_pause=True,
    )
    return {"queued": False, "status": status, **(result or {})}


@router.get("/logs")
def get_bot_logs(
    limit: int = Query(default=50, ge=1, le=200),
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return [
        {
            "id": r.id,
            "bot_name": r.bot_name,
            "queue_name": r.queue_name,
            "task_id": r.task_id,
            "status": r.status,
            "attempt": r.attempt,
            "duration_ms": r.duration_ms,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "error_message": r.error_message,
        }
        for r in db.scalars(select(BotRun).order_by(BotRun.started_at.desc()).limit(limit))
    ]
