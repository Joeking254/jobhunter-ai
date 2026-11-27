from datetime import datetime, timezone
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_csrf
from app.core.config import settings
from app.models.models import (
    Application,
    JobMatch,
    JobSource,
    Opportunity,
    SourceExecutionHistory,
    User,
)
from app.services.ai.matching import match_opportunity
from app.services.discovery.runner import run_all_sources, run_source

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


class DiscoverRequest(BaseModel):
    source_id: str | None = None
    run_matching: bool = True


def _serialize_opportunity(
    opp: Opportunity,
    source: JobSource | None,
    match: JobMatch | None,
    application: Application | None,
) -> dict[str, Any]:
    analysis = {}
    if match and match.analysis_json:
        try:
            analysis = json.loads(match.analysis_json)
        except json.JSONDecodeError:
            analysis = {}
    return {
        "id": opp.id,
        "source_id": opp.source_id,
        "source_name": source.name if source else None,
        "title": opp.title,
        "company": opp.company,
        "location": opp.location,
        "url": opp.url,
        "description": opp.description,
        "posted_at": opp.posted_at,
        "deadline": opp.deadline,
        "salary_text": opp.salary_text,
        "salary_min": opp.salary_min,
        "salary_max": opp.salary_max,
        "salary_currency": opp.salary_currency,
        "remote_only": opp.remote_only,
        "categories": opp.categories,
        "expired_at": opp.expired_at,
        "match_score": match.score if match else None,
        "eligible": match.eligible if match else None,
        "risk_level": match.risk_level if match else None,
        "match_explanation": match.explanation if match else None,
        "missing_skills": analysis.get("missing_skills", []),
        "matching_skills": analysis.get("matching_skills", []),
        "risk_warnings": analysis.get("risk_warnings", []),
        "recommended_next_action": match.next_action if match else None,
        "application_id": application.id if application else None,
        "application_status": application.status if application else "discovered",
    }


@router.get("")
def list_opportunities(
    q: str | None = Query(default=None),
    location: str | None = Query(default=None),
    remote_only: bool | None = Query(default=None),
    source_id: str | None = Query(default=None),
    category: str | None = Query(default=None),
    recommended_only: bool = Query(default=False),
    min_score: int | None = Query(default=None, ge=0, le=100),
    application_status: str | None = Query(default=None),
    active_only: bool = Query(default=False),
    sort_by: str = Query(default="score"),
    sort_dir: str = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=12, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    sources = {s.id: s for s in db.scalars(select(JobSource))}
    matches = {
        m.opportunity_id: m
        for m in db.scalars(select(JobMatch).where(JobMatch.user_id == user.id))
    }
    apps = {
        a.opportunity_id: a
        for a in db.scalars(select(Application).where(Application.user_id == user.id))
    }

    rows: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    q_clean = (q or "").strip()
    loc_clean = (location or "").strip()
    cat_clean = (category or "").strip()

    opp_stmt = select(Opportunity)
    if active_only:
        opp_stmt = opp_stmt.where(Opportunity.expired_at.is_(None))
    if remote_only is True:
        opp_stmt = opp_stmt.where(Opportunity.remote_only.is_(True))
    if source_id:
        opp_stmt = opp_stmt.where(Opportunity.source_id == source_id)
    if q_clean:
        pattern = f"%{q_clean}%"
        opp_stmt = opp_stmt.where(
            or_(
                Opportunity.title.ilike(pattern),
                Opportunity.company.ilike(pattern),
                Opportunity.description.ilike(pattern),
            )
        )
    if loc_clean:
        opp_stmt = opp_stmt.where(Opportunity.location.ilike(f"%{loc_clean}%"))
    if cat_clean:
        opp_stmt = opp_stmt.where(Opportunity.categories.ilike(f"%{cat_clean}%"))

    for opp in db.scalars(opp_stmt):
        match = matches.get(opp.id)
        app = apps.get(opp.id)
        source = sources.get(opp.source_id)
        item = _serialize_opportunity(opp, source, match, app)

        if active_only and opp.deadline is not None:
            dl = opp.deadline.astimezone(timezone.utc) if opp.deadline.tzinfo else opp.deadline.replace(tzinfo=timezone.utc)
            if dl < now:
                continue
        if recommended_only and not (match and match.eligible and match.score >= settings.match_approval_threshold):
            continue
        if min_score is not None and (match is None or match.score < min_score):
            continue
        if application_status and item["application_status"] != application_status:
            continue
        rows.append(item)

    reverse = sort_dir.lower() != "asc"

    def _sort_key(row: dict[str, Any]):
        if sort_by == "score":
            return (row["match_score"] if row["match_score"] is not None else -1, row["title"].lower())
        if sort_by == "company":
            return row["company"].lower()
        if sort_by == "deadline":
            dt = row["deadline"]
            return dt.timestamp() if dt else float("inf")
        if sort_by == "salary_max":
            return row["salary_max"] or 0
        dt = row["posted_at"]
        return dt.timestamp() if dt else 0.0

    rows.sort(key=_sort_key, reverse=reverse)
    total = len(rows)
    total_pages = max(1, (total + page_size - 1) // page_size)
    offset = (page - 1) * page_size
    return {
        "items": rows[offset : offset + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.post("/discover")
def trigger_discovery(
    payload: DiscoverRequest,
    user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if payload.source_id:
        source = db.get(JobSource, payload.source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Source not found")
        histories = [run_source(db, source)]
    else:
        histories = run_all_sources(db)

    matched = 0
    if payload.run_matching:
        for opp in db.scalars(select(Opportunity).where(Opportunity.expired_at.is_(None))):
            match_opportunity(db, user, opp)
            matched += 1

    return {
        "runs": len(histories),
        "fetched": sum(h.fetched_count for h in histories),
        "created": sum(h.created_count for h in histories),
        "updated": sum(h.updated_count for h in histories),
        "matched": matched,
    }


@router.get("/discovery-history")
def discovery_history(
    limit: int = Query(default=25, ge=1, le=100),
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    sources = {s.id: s.name for s in db.scalars(select(JobSource))}
    rows = db.scalars(select(SourceExecutionHistory).order_by(SourceExecutionHistory.started_at.desc()).limit(limit))
    return [
        {
            "id": row.id,
            "source_id": row.source_id,
            "source_name": sources.get(row.source_id, "Unknown"),
            "status": row.status,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
            "fetched_count": row.fetched_count,
            "created_count": row.created_count,
            "updated_count": row.updated_count,
            "error_message": row.error_message,
        }
        for row in rows
    ]
