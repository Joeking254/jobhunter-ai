import hashlib
import json
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import AIProcessingHistory, Opportunity
from app.services.ai.providers import RuleBasedProvider, get_provider

logger = logging.getLogger(__name__)


def _input_hash(opportunity: Opportunity) -> str:
    source = json.dumps({"title": opportunity.title, "company": opportunity.company, "description": opportunity.description, "experience": opportunity.experience_requirements, "salary": opportunity.salary_text}, sort_keys=True)
    return hashlib.sha256(source.encode()).hexdigest()


def analyze_opportunity(db: Session, opportunity: Opportunity) -> dict:
    input_hash = _input_hash(opportunity)
    cached = db.scalar(select(AIProcessingHistory).where(AIProcessingHistory.entity_type == "job_analysis", AIProcessingHistory.entity_id == opportunity.id, AIProcessingHistory.input_hash == input_hash, AIProcessingHistory.status == "success").order_by(AIProcessingHistory.created_at.desc()))
    if cached:
        return json.loads(cached.output or "{}")
    provider = get_provider()
    payload = {"title": opportunity.title, "company": opportunity.company, "description": opportunity.description, "experience_requirements": opportunity.experience_requirements, "salary_text": opportunity.salary_text, "salary_min": opportunity.salary_min, "salary_max": opportunity.salary_max, "salary_currency": opportunity.salary_currency}
    processor_name = provider.name
    try:
        output = provider.analyze_job(payload)
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        logger.warning("AI analysis provider failed; falling back to rules", extra={"provider": provider.name, "error": type(exc).__name__})
        db.add(AIProcessingHistory(user_id=None, entity_type="job_analysis", entity_id=opportunity.id, processor=provider.name, status="failed", input_hash=input_hash, output=json.dumps({"error": type(exc).__name__})))
        fallback = RuleBasedProvider()
        processor_name = f"{fallback.name}_fallback"
        output = fallback.analyze_job(payload)
    output.setdefault("job_category", "IT")
    output.setdefault("required_skills", [])
    output.setdefault("education_requirements", [])
    output.setdefault("eligibility_restrictions", [])
    output.setdefault("experience_requirements", None)
    output.setdefault("risk_warnings", [])
    output.setdefault("risk_level", "low")
    output.setdefault("salary", {})
    db.add(AIProcessingHistory(user_id=None, entity_type="job_analysis", entity_id=opportunity.id, processor=processor_name, status="success", input_hash=input_hash, output=json.dumps(output)))
    db.commit()
    return output
