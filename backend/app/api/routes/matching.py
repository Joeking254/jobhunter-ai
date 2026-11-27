from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_csrf
from app.models.models import Opportunity, User
from app.services.ai.matching import match_opportunity

router = APIRouter(prefix="/matching", tags=["matching"])


@router.post("/opportunities/{opportunity_id}/analyze")
def analyze_match(opportunity_id: str, user: User = Depends(get_current_user), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    opportunity = db.get(Opportunity, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return match_opportunity(db, user, opportunity)


@router.get("/opportunities/{opportunity_id}")
def get_match(opportunity_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    opportunity = db.get(Opportunity, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    from app.models.models import JobMatch
    match = db.scalar(select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.opportunity_id == opportunity.id))
    if match is None or not match.analysis_json:
        raise HTTPException(status_code=404, detail="Opportunity has not been analyzed")
    import json
    return json.loads(match.analysis_json)


@router.post("/run")
def run_matching(user: User = Depends(get_current_user), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> dict[str, int]:
    opportunities = db.scalars(select(Opportunity).where(Opportunity.expired_at.is_(None))).all()
    processed = sum(1 for opportunity in opportunities if match_opportunity(db, user, opportunity))
    return {"processed": processed}
