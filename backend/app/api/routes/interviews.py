from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_csrf
from app.models.models import Application, Interview, Opportunity, User
from app.services.notifications.service import notify_interview_invitation

router = APIRouter(prefix="/interviews", tags=["interviews"])


class InterviewCreate(BaseModel):
    application_id: str
    scheduled_at: datetime
    interview_type: str | None = Field(default="technical", max_length=80)
    notes: str | None = None


class InterviewUpdate(BaseModel):
    scheduled_at: datetime | None = None
    interview_type: str | None = Field(default=None, max_length=80)
    notes: str | None = None


def _serialize(interview: Interview, application: Application | None, opp: Opportunity | None) -> dict[str, Any]:
    return {
        "id": interview.id,
        "application_id": interview.application_id,
        "scheduled_at": interview.scheduled_at,
        "interview_type": interview.interview_type,
        "notes": interview.notes,
        "title": opp.title if opp else None,
        "company": opp.company if opp else None,
        "application_status": application.status if application else None,
    }


@router.get("")
def list_interviews(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Interview, Application, Opportunity)
        .join(Application, Application.id == Interview.application_id)
        .join(Opportunity, Opportunity.id == Application.opportunity_id)
        .where(Application.user_id == user.id)
        .order_by(Interview.scheduled_at.asc())
    ).all()
    return [_serialize(interview, app, opp) for interview, app, opp in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_interview(
    payload: InterviewCreate,
    user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    application = db.scalar(select(Application).where(Application.id == payload.application_id, Application.user_id == user.id))
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    interview = Interview(
        application_id=application.id,
        scheduled_at=payload.scheduled_at,
        interview_type=payload.interview_type,
        notes=payload.notes,
    )
    db.add(interview)
    db.commit()
    db.refresh(interview)
    notify_interview_invitation(db, user, interview)
    opp = db.get(Opportunity, application.opportunity_id)
    return _serialize(interview, application, opp)


@router.put("/{interview_id}")
def update_interview(
    interview_id: str,
    payload: InterviewUpdate,
    user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    row = db.execute(
        select(Interview, Application, Opportunity)
        .join(Application, Application.id == Interview.application_id)
        .join(Opportunity, Opportunity.id == Application.opportunity_id)
        .where(Interview.id == interview_id, Application.user_id == user.id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Interview not found")
    interview, application, opp = row
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(interview, field, value)
    db.commit()
    return _serialize(interview, application, opp)


@router.delete("/{interview_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_interview(
    interview_id: str,
    user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> None:
    interview = db.scalar(
        select(Interview)
        .join(Application, Application.id == Interview.application_id)
        .where(Interview.id == interview_id, Application.user_id == user.id)
    )
    if interview is None:
        raise HTTPException(status_code=404, detail="Interview not found")
    db.delete(interview)
    db.commit()
