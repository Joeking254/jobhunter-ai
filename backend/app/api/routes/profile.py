import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_csrf
from app.core.security import utcnow
from app.models.models import CareerProfile, Education, Experience, ProfileFact, Skill, User
from app.schemas.profile import EducationInput, ExperienceInput, ProfileUpdate, SkillInput

router = APIRouter(prefix="/profile", tags=["profile"])


def _profile(db: Session, user: User) -> CareerProfile:
    profile = db.scalar(select(CareerProfile).where(CareerProfile.user_id == user.id))
    if profile is None:
        profile = CareerProfile(user_id=user.id)
        db.add(profile)
        db.flush()
    return profile


def _completeness(user: User, profile: CareerProfile, education: list[Education], experience: list[Experience], skills: list[Skill], default_cv: bool) -> int:
    checks = [bool(user.first_name and user.last_name and user.email), bool(profile.phone and profile.country and profile.city), bool(profile.professional_summary), bool(profile.linkedin_url or profile.portfolio_links), bool(education), bool(experience), bool(skills), default_cv]
    return round(sum(checks) / len(checks) * 100)


@router.get("")
def get_profile(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    profile = _profile(db, user)
    education = list(db.scalars(select(Education).where(Education.user_id == user.id).order_by(Education.start_date)))
    experience = list(db.scalars(select(Experience).where(Experience.user_id == user.id).order_by(Experience.start_date)))
    skills = list(db.scalars(select(Skill).where(Skill.user_id == user.id).order_by(Skill.category, Skill.name)))
    default_cv = db.scalar(select(ProfileFact.id).where(ProfileFact.user_id == user.id, ProfileFact.field_key == "default_cv")) is not None
    return {
        "personal": {"first_name": user.first_name, "last_name": user.last_name, "email": user.email, "phone": profile.phone, "country": profile.country, "city": profile.city, "professional_summary": profile.professional_summary, "portfolio_links": json.loads(profile.portfolio_links or "[]"), "linkedin_url": profile.linkedin_url},
        "education": [{"id": item.id, "institution": item.institution, "qualification": item.qualification, "field_of_study": item.field_of_study, "start_date": item.start_date, "end_date": item.end_date, "current_status": item.current_status} for item in education],
        "experience": [{"id": item.id, "company": item.company, "title": item.title, "employment_type": item.employment_type, "description": item.description, "achievements": item.achievements, "start_date": item.start_date, "end_date": item.end_date} for item in experience],
        "skills": [{"id": item.id, "name": item.name, "category": item.category, "proficiency": item.proficiency, "years_experience": item.years_experience} for item in skills],
        "completeness_score": _completeness(user, profile, education, experience, skills, default_cv),
    }


@router.put("")
def update_profile(payload: ProfileUpdate, user: User = Depends(get_current_user), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    profile = _profile(db, user)
    values = payload.model_dump(exclude_unset=True)
    if "email" in values:
        existing = db.scalar(select(User).where(User.email == str(values["email"]).lower(), User.id != user.id))
        if existing:
            raise HTTPException(status_code=409, detail="An account with this email already exists")
        values["email"] = str(values["email"]).lower()
    for field in ("first_name", "last_name", "email"):
        if field in values:
            setattr(user, field, values.pop(field))
    if "portfolio_links" in values:
        values["portfolio_links"] = json.dumps([str(link) for link in values["portfolio_links"]])
    if "linkedin_url" in values and values["linkedin_url"] is not None:
        values["linkedin_url"] = str(values["linkedin_url"])
    for field, value in values.items():
        setattr(profile, field, value)
        db.add(ProfileFact(user_id=user.id, field_key=field, value=json.dumps(value) if isinstance(value, list) else str(value or ""), source="user", status="confirmed", verified_at=utcnow()))
    db.commit()
    return get_profile(user, db)


@router.post("/education", status_code=status.HTTP_201_CREATED)
def add_education(payload: EducationInput, user: User = Depends(get_current_user), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    item = Education(user_id=user.id, **payload.model_dump())
    db.add(item)
    db.commit()
    return {"id": item.id}


@router.post("/experience", status_code=status.HTTP_201_CREATED)
def add_experience(payload: ExperienceInput, user: User = Depends(get_current_user), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    item = Experience(user_id=user.id, **payload.model_dump())
    db.add(item)
    db.commit()
    return {"id": item.id}


@router.post("/skills", status_code=status.HTTP_201_CREATED)
def add_skill(payload: SkillInput, user: User = Depends(get_current_user), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    item = Skill(user_id=user.id, **payload.model_dump())
    db.add(item)
    db.commit()
    return {"id": item.id}


@router.get("/facts")
def get_facts(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [{"id": fact.id, "field_key": fact.field_key, "value": fact.value, "status": fact.status, "source": fact.source, "evidence_document_id": fact.evidence_document_id} for fact in db.scalars(select(ProfileFact).where(ProfileFact.user_id == user.id).order_by(ProfileFact.created_at.desc()))]


@router.post("/facts/{fact_id}/confirm")
def confirm_fact(fact_id: str, user: User = Depends(get_current_user), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> dict[str, str]:
    fact = db.scalar(select(ProfileFact).where(ProfileFact.id == fact_id, ProfileFact.user_id == user.id))
    if fact is None:
        raise HTTPException(status_code=404, detail="Fact not found")
    fact.status = "confirmed"
    fact.verified_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "confirmed"}


@router.delete("/education/{item_id}")
def delete_education(item_id: str, user: User = Depends(get_current_user), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> dict[str, str]:
    item = db.scalar(select(Education).where(Education.id == item_id, Education.user_id == user.id))
    if item is None:
        raise HTTPException(status_code=404, detail="Education item not found")
    db.delete(item)
    db.commit()
    return {"status": "deleted"}


@router.delete("/experience/{item_id}")
def delete_experience(item_id: str, user: User = Depends(get_current_user), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> dict[str, str]:
    item = db.scalar(select(Experience).where(Experience.id == item_id, Experience.user_id == user.id))
    if item is None:
        raise HTTPException(status_code=404, detail="Experience item not found")
    db.delete(item)
    db.commit()
    return {"status": "deleted"}


@router.delete("/skills/{item_id}")
def delete_skill(item_id: str, user: User = Depends(get_current_user), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> dict[str, str]:
    item = db.scalar(select(Skill).where(Skill.id == item_id, Skill.user_id == user.id))
    if item is None:
        raise HTTPException(status_code=404, detail="Skill item not found")
    db.delete(item)
    db.commit()
    return {"status": "deleted"}
