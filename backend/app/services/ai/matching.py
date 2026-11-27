import json
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import BotConfig, CareerProfile, Document, Education, Experience, JobMatch, Opportunity, Skill, User, UserSettings
from app.services.ai.analysis import analyze_opportunity


def _text(value: str | None) -> str:
    return (value or "").lower()


def _tokens(values: list[str]) -> set[str]:
    return {value.strip().lower() for value in values if value and value.strip()}


def match_opportunity(db: Session, user: User, opportunity: Opportunity) -> dict:
    analysis = analyze_opportunity(db, opportunity)
    profile = db.scalar(select(CareerProfile).where(CareerProfile.user_id == user.id))
    settings_row = db.scalar(select(UserSettings).where(UserSettings.user_id == user.id))
    skills = list(db.scalars(select(Skill).where(Skill.user_id == user.id)))
    education = list(db.scalars(select(Education).where(Education.user_id == user.id)))
    experience = list(db.scalars(select(Experience).where(Experience.user_id == user.id)))
    profile_skills = _tokens([skill.name for skill in skills])
    required_skills = _tokens(analysis.get("required_skills", []))
    matching_skills = sorted(required_skills & profile_skills)
    missing_skills = sorted(required_skills - profile_skills)
    skills_score = 100 if not required_skills else round(len(matching_skills) / len(required_skills) * 100)
    education_text = " ".join(_text(item.qualification or item.degree) + " " + _text(item.field_of_study) for item in education)
    education_requirements = [_text(item) for item in analysis.get("education_requirements", [])]
    education_score = 100 if not education_requirements or all(any(requirement in education_text for _ in [0]) for requirement in education_requirements) else 0
    experience_text = " ".join(_text(item.title) + " " + _text(item.description) for item in experience)
    required_years_match = re.search(r"(\d+)\+?\s+years?", _text(analysis.get("experience_requirements")))
    total_years = sum(skill.years_experience or 0 for skill in skills)
    experience_score = 100 if not required_years_match or total_years >= int(required_years_match.group(1)) or bool(experience_text) else 0
    location_text = " ".join((_text(profile.city if profile else None), _text(profile.country if profile else None), _text(settings_row.preferred_locations if settings_row else None)))
    location_score = 100 if opportunity.remote_only or not opportunity.location or any(part and part in _text(opportunity.location) for part in location_text.split()) else 0
    authorization_required = bool(analysis.get("eligibility_restrictions"))
    authorization_score = 100 if not authorization_required or (settings_row and settings_row.work_authorization) else 0
    type_score = 100 if not settings_row or not settings_row.opportunity_types or any(value.strip().lower() in _text(opportunity.categories) for value in settings_row.opportunity_types.split(",")) else 0
    preference_score = 100 if not settings_row or not settings_row.career_preferences or any(value.strip().lower() in _text(opportunity.title) for value in settings_row.career_preferences.split(",")) else 0
    weighted = round((skills_score * settings.match_weight_skills + education_score * settings.match_weight_education + experience_score * settings.match_weight_experience + location_score * settings.match_weight_location + authorization_score * settings.match_weight_authorization + type_score * settings.match_weight_type + preference_score * settings.match_weight_preference) / 100)
    bot_cfg = db.scalar(select(BotConfig).where(BotConfig.scope_key == "global"))
    strong_threshold = bot_cfg.match_strong_threshold if bot_cfg else settings.match_strong_threshold
    approval_threshold = bot_cfg.match_approval_threshold if bot_cfg else settings.match_approval_threshold
    expired = bool(opportunity.expired_at or (opportunity.deadline and opportunity.deadline.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc)))
    eligible = authorization_score == 100 and not expired and (not settings_row or not settings_row.remote_only or opportunity.remote_only)
    score = weighted if eligible else 0
    label = "Strong match" if score >= strong_threshold else "Approval required" if score >= approval_threshold else "Not recommended"
    if not eligible:
        label = "Ineligible" if not expired else "Expired"
    default_cv = db.scalar(select(Document).where(Document.user_id == user.id, Document.document_type == "cv", Document.is_default.is_(True)))
    result = {"job_category": analysis["job_category"], "required_skills": sorted(required_skills), "matching_skills": matching_skills, "missing_skills": missing_skills, "eligibility_assessment": {"eligible": eligible, "label": label, "location_score": location_score, "authorization_score": authorization_score}, "experience_requirements": analysis.get("experience_requirements"), "match_score": score, "risk_warnings": analysis.get("risk_warnings", []), "explanation": f"Matched {len(matching_skills)} of {len(required_skills)} required skills; eligibility rules were applied before scoring.", "recommended_cv": default_cv.id if default_cv else None, "recommended_next_action": "Apply" if score >= strong_threshold else "Request approval" if score >= approval_threshold and eligible else "Do not apply"}
    existing = db.scalar(select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.opportunity_id == opportunity.id))
    if existing is None:
        existing = JobMatch(user_id=user.id, opportunity_id=opportunity.id, score=score)
        db.add(existing)
    existing.score = score
    existing.eligible = eligible
    existing.risk_level = analysis.get("risk_level")
    existing.analysis_json = json.dumps(result)
    existing.explanation = result["explanation"]
    existing.recommended_cv_id = default_cv.id if default_cv else None
    existing.next_action = result["recommended_next_action"]
    db.commit()
    if eligible and score >= strong_threshold:
        from app.services.notifications.service import notify_strong_match
        notify_strong_match(db, user, opportunity, existing)
    return result
