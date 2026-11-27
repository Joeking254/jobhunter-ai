from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_csrf
from app.core.config import settings
from app.models.models import (
    Application,
    Interview,
    JobMatch,
    JobSource,
    Opportunity,
    User,
    UserSettings,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class AIConfigUpdate(BaseModel):
    work_authorization: str | None = Field(default=None, max_length=120)
    preferred_locations: str | None = None
    remote_only: bool | None = None
    opportunity_types: str | None = None
    career_preferences: str | None = None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


@router.get("/overview")
def get_overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(days=7)

    opportunities = list(db.scalars(select(Opportunity)))
    total_opportunities = len(opportunities)
    new_opportunities = sum(
        1
        for opp in opportunities
        if (ts := _as_utc(opp.created_at)) is not None and ts >= recent_cutoff
    )

    matches = list(db.scalars(select(JobMatch).where(JobMatch.user_id == user.id)))
    strong_matches = sum(1 for m in matches if m.eligible and m.score >= settings.match_strong_threshold)
    recommended_matches = sum(1 for m in matches if m.eligible and m.score >= settings.match_approval_threshold)

    applications = list(db.scalars(select(Application).where(Application.user_id == user.id)))
    status_counts = Counter(app.status for app in applications)
    pending_approvals = status_counts.get("pending_approval", 0)
    submitted_applications = status_counts.get("submitted", 0)
    rejected_applications = status_counts.get("rejected", 0)
    failed_applications = status_counts.get("failed", 0)
    confirmation_pending = status_counts.get("confirmation_pending", 0)

    interview_invitations = int(
        db.scalar(
            select(func.count(Interview.id))
            .join(Application, Application.id == Interview.application_id)
            .where(Application.user_id == user.id)
        )
        or 0
    )

    attempted_total = submitted_applications + failed_applications + confirmation_pending
    submission_success_rate = round((submitted_applications / attempted_total) * 100, 1) if attempted_total else 0.0
    interview_rate = round((interview_invitations / submitted_applications) * 100, 1) if submitted_applications else 0.0
    approval_decisions = submitted_applications + status_counts.get("approved", 0) + rejected_applications
    approval_rate = round(((submitted_applications + status_counts.get("approved", 0)) / approval_decisions) * 100, 1) if approval_decisions else 0.0

    return {
        "total_opportunities": total_opportunities,
        "new_opportunities": new_opportunities,
        "strong_matches": strong_matches,
        "recommended_matches": recommended_matches,
        "pending_approvals": pending_approvals,
        "applications_submitted": submitted_applications,
        "interview_invitations": interview_invitations,
        "rejected_applications": rejected_applications,
        "failed_applications": failed_applications,
        "confirmation_pending": confirmation_pending,
        "success_statistics": {
            "submission_success_rate_pct": submission_success_rate,
            "interview_conversion_rate_pct": interview_rate,
            "approval_rate_pct": approval_rate,
            "total_applications": len(applications),
        },
        "status_breakdown": dict(status_counts),
    }


@router.get("/analytics")
def get_analytics(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    opportunities = list(db.scalars(select(Opportunity)))
    sources = {s.id: s for s in db.scalars(select(JobSource))}
    matches = list(db.scalars(select(JobMatch).where(JobMatch.user_id == user.id)))
    applications = list(db.scalars(select(Application).where(Application.user_id == user.id)))
    interviews = list(
        db.scalars(
            select(Interview)
            .join(Application, Application.id == Interview.application_id)
            .where(Application.user_id == user.id)
        )
    )

    opp_by_id = {opp.id: opp for opp in opportunities}
    match_by_opp = {m.opportunity_id: m for m in matches}
    app_by_opp = {a.opportunity_id: a for a in applications}

    # 1. Opportunities discovered by week
    weekly_opps: dict[str, int] = defaultdict(int)
    for opp in opportunities:
        dt = _as_utc(opp.created_at)
        if dt:
            iso = dt.isocalendar()
            weekly_opps[f"{iso.year}-W{iso.week:02d}"] += 1
    opportunities_by_week = [{"week": week, "count": weekly_opps[week]} for week in sorted(weekly_opps)]

    # 2. Applications submitted (by week + status totals)
    weekly_submitted: dict[str, int] = defaultdict(int)
    for app in applications:
        if app.status == "submitted":
            dt = _as_utc(app.submitted_at or app.updated_at or app.created_at)
            if dt:
                iso = dt.isocalendar()
                weekly_submitted[f"{iso.year}-W{iso.week:02d}"] += 1
    applications_submitted_weekly = [{"week": w, "count": weekly_submitted[w]} for w in sorted(weekly_submitted)]

    # 3. Applications by category
    category_counts: dict[str, int] = defaultdict(int)
    for app in applications:
        opp = opp_by_id.get(app.opportunity_id)
        match = match_by_opp.get(app.opportunity_id)
        cat = "Uncategorized"
        if match and match.analysis_json:
            try:
                cat = json.loads(match.analysis_json).get("job_category") or cat
            except json.JSONDecodeError:
                pass
        elif opp and opp.categories:
            cat = opp.categories.split(",")[0].strip() or cat
        category_counts[cat] += 1
    applications_by_category = [
        {"category": cat, "count": count}
        for cat, count in sorted(category_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    # 4. Interview conversion
    submitted_count = sum(1 for a in applications if a.status == "submitted")
    interview_count = len(interviews)
    interview_conversion = {
        "matched": len(matches),
        "prepared": len(applications),
        "submitted": submitted_count,
        "interviews": interview_count,
        "conversion_rate_pct": round((interview_count / submitted_count) * 100, 1) if submitted_count else 0.0,
    }

    # 5. Source performance
    source_stats: dict[str, dict[str, Any]] = {}
    for s in sources.values():
        source_stats[s.id] = {
            "source_id": s.id,
            "name": s.name,
            "reliability_score": s.reliability_score,
            "opportunities": 0,
            "strong_matches": 0,
            "applications": 0,
            "submitted": 0,
        }
    for opp in opportunities:
        bucket = source_stats.get(opp.source_id)
        if not bucket:
            continue
        bucket["opportunities"] += 1
        m = match_by_opp.get(opp.id)
        if m and m.eligible and m.score >= settings.match_strong_threshold:
            bucket["strong_matches"] += 1
        app = app_by_opp.get(opp.id)
        if app:
            bucket["applications"] += 1
            if app.status == "submitted":
                bucket["submitted"] += 1
    source_performance = sorted(source_stats.values(), key=lambda x: (-x["opportunities"], x["name"]))

    # 6. Match distribution
    buckets = {"0-39": 0, "40-64": 0, "65-84": 0, "85-100": 0}
    for m in matches:
        if m.score >= 85:
            buckets["85-100"] += 1
        elif m.score >= 65:
            buckets["65-84"] += 1
        elif m.score >= 40:
            buckets["40-64"] += 1
        else:
            buckets["0-39"] += 1
    match_distribution = [{"range": k, "count": v} for k, v in buckets.items()]

    return {
        "opportunities_by_week": opportunities_by_week,
        "applications_submitted": applications_submitted_weekly,
        "applications_by_category": applications_by_category,
        "interview_conversion": interview_conversion,
        "source_performance": source_performance,
        "match_distribution": match_distribution,
    }


@router.get("/ai-config")
def get_ai_config(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.scalar(select(UserSettings).where(UserSettings.user_id == user.id))
    if row is None:
        row = UserSettings(user_id=user.id)
        db.add(row)
        db.commit()
    from app.services.ai.providers import resolved_ai_model

    return {
        "ai_provider": settings.ai_provider,
        "ai_model": resolved_ai_model(),
        "thresholds": {
            "strong_match": settings.match_strong_threshold,
            "approval_required": settings.match_approval_threshold,
        },
        "weights": {
            "skills": settings.match_weight_skills,
            "education": settings.match_weight_education,
            "experience": settings.match_weight_experience,
            "location": settings.match_weight_location,
            "authorization": settings.match_weight_authorization,
            "type": settings.match_weight_type,
            "preference": settings.match_weight_preference,
        },
        "preferences": {
            "work_authorization": row.work_authorization,
            "preferred_locations": row.preferred_locations,
            "remote_only": bool(row.remote_only),
            "opportunity_types": row.opportunity_types,
            "career_preferences": row.career_preferences,
        },
    }


@router.put("/ai-config")
def update_ai_config(
    payload: AIConfigUpdate,
    user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    row = db.scalar(select(UserSettings).where(UserSettings.user_id == user.id))
    if row is None:
        row = UserSettings(user_id=user.id)
        db.add(row)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    return get_ai_config(user, db)
