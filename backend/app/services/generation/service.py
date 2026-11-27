import hashlib
import json
import logging
import re
import secrets
from io import BytesIO
from pathlib import Path

from docx import Document as DocxDocument
import httpx
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import AIProcessingHistory, CareerProfile, Document, Education, Experience, GeneratedDocument, Opportunity, Skill, User
from app.services.ai.analysis import analyze_opportunity
from app.services.generation.providers import VerifiedTemplateProvider, get_generation_provider

logger = logging.getLogger(__name__)

TEMPLATES = {"ict_internship": "ICT internship", "software_development": "Software development", "ai_training": "AI training", "data_annotation": "Data annotation", "technical_support": "Technical support", "graphic_design": "Graphic design", "digital_marketing": "Digital marketing", "entry_level": "General entry-level employment"}


def select_template(opportunity: Opportunity, analysis: dict) -> str:
    text = f"{opportunity.title} {analysis.get('job_category', '')}".lower()
    for key, label in TEMPLATES.items():
        if key.replace("_", " ") in text or label.lower() in text:
            return key
    return "entry_level"


def verified_context(db: Session, user: User, opportunity: Opportunity, questions: list[str]) -> dict:
    profile = db.scalar(select(CareerProfile).where(CareerProfile.user_id == user.id))
    education = list(db.scalars(select(Education).where(Education.user_id == user.id)))
    experience = list(db.scalars(select(Experience).where(Experience.user_id == user.id)))
    skills = list(db.scalars(select(Skill).where(Skill.user_id == user.id)))
    return {"job": {"title": opportunity.title, "company": opportunity.company, "description": opportunity.description or "", "url": opportunity.url}, "profile": {"first_name": user.first_name, "last_name": user.last_name, "email": user.email, "phone": profile.phone if profile else None, "city": profile.city if profile else None, "professional_summary": profile.professional_summary if profile else None, "skills": [skill.name for skill in skills], "education": [{"qualification": item.qualification, "degree": item.degree, "field_of_study": item.field_of_study} for item in education], "experience": [{"company": item.company, "title": item.title, "start_date": str(item.start_date) if item.start_date else None, "end_date": str(item.end_date) if item.end_date else None} for item in experience]}, "questions": questions}


def unsupported_claims(text: str, context: dict) -> list[str]:
    profile = context["profile"]
    allowed = " ".join([profile["first_name"], profile["last_name"], profile["email"], profile.get("professional_summary") or "", *profile["skills"], *[item["company"] + " " + item["title"] for item in profile["experience"]], *[str(item.get("qualification") or item.get("degree") or "") for item in profile["education"]]])
    claims = []
    for match in re.finditer(r"(?:worked|employed|interned)\s+(?:at|with)\s+([A-Za-z][A-Za-z0-9 &.-]*?)(?:\s+in\s+\d{4}|[.,]|$)", text, re.IGNORECASE):
        value = match.group(1).strip(" .,")
        if value.lower() not in allowed.lower():
            claims.append(value)
    for year in re.findall(r"\b(?:19|20)\d{2}\b", text):
        if year not in allowed:
            claims.append(year)
    return claims


def _write_file(text: str, fmt: str, path: Path) -> str:
    if fmt == "docx":
        document = DocxDocument()
        for line in text.splitlines():
            document.add_paragraph(line)
        document.save(path)
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    pdf = canvas.Canvas(str(path), pagesize=LETTER)
    y = 750
    for line in text.splitlines():
        pdf.drawString(54, y, line[:110])
        y -= 15
        if y < 54:
            pdf.showPage()
            y = 750
    pdf.save()
    return "application/pdf"


def generate_documents(db: Session, user: User, opportunity: Opportunity, questions: list[str] | None = None, formats: list[str] | None = None) -> list[GeneratedDocument]:
    questions = questions or []
    formats = formats or ["docx", "pdf"]
    analysis = analyze_opportunity(db, opportunity)
    context = verified_context(db, user, opportunity, questions)
    provider = get_generation_provider()
    try:
        generated = provider.generate(context)
    except (httpx.HTTPError, ValueError, RuntimeError, KeyError, IndexError) as exc:
        logger.warning("Generation provider failed; falling back to verified template", extra={"error": type(exc).__name__})
        db.add(AIProcessingHistory(user_id=user.id, entity_type="document_generation", entity_id=opportunity.id, processor=type(provider).__name__, status="failed", output=json.dumps({"error": type(exc).__name__})))
        generated = VerifiedTemplateProvider().generate(context)
    outputs = [("cv", str(generated["cv"])), ("cover_letter", str(generated["cover_letter"])), ("application_answers", json.dumps(generated.get("answers", {}), indent=2))]
    template_name = select_template(opportunity, analysis)
    prompt_hash = hashlib.sha256(json.dumps(context, sort_keys=True, default=str).encode()).hexdigest()
    results = []
    for document_type, text in outputs:
        claims = unsupported_claims(text, context)
        if claims:
            raise ValueError(f"Generated content contains unsupported claims: {claims}")
        for fmt in formats:
            if fmt not in {"pdf", "docx"}:
                raise ValueError("Only PDF and DOCX formats are supported")
            version = int(db.scalar(select(func.max(GeneratedDocument.version)).where(GeneratedDocument.user_id == user.id, GeneratedDocument.opportunity_id == opportunity.id, GeneratedDocument.document_type == document_type, GeneratedDocument.file_format == fmt)) or 0) + 1
            document_id = secrets.token_hex(16)
            root = (Path(settings.document_storage_dir).resolve() / user.id)
            root.mkdir(parents=True, exist_ok=True)
            storage_key = f"generated-{document_id}.{fmt}"
            path = root / storage_key
            mime_type = _write_file(text, fmt, path)
            source_document = Document(id=document_id, user_id=user.id, name=f"{document_type}-v{version}.{fmt}", document_type=f"generated_{document_type}", storage_key=storage_key, content_hash=hashlib.sha256(text.encode()).hexdigest(), mime_type=mime_type, size_bytes=path.stat().st_size, extracted_text=text)
            db.add(source_document)
            row = GeneratedDocument(user_id=user.id, opportunity_id=opportunity.id, document_id=document_id, document_type=document_type, file_format=fmt, template_name=template_name, version=version, editable_text=text, prompt_hash=prompt_hash, claims_json=json.dumps({"unsupported": claims}), generation_status="ready")
            db.add(row)
            results.append(row)
    db.commit()
    return results
