import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_csrf
from app.core.config import settings
from app.models.models import (
    Application,
    ApplicationAnswer,
    ApplicationAttempt,
    ApprovalRequest,
    AuditLog,
    Document,
    GeneratedDocument,
    JobMatch,
    Opportunity,
    User,
)
from app.services.application.automation import PlaywrightBrowserAdapter
from app.services.application.engine import (
    _latest_generated_doc,
    _record_audit,
    count_application_statuses,
    now,
    preflight,
    prepare_application,
    submit_application,
)
from app.services.generation.service import _write_file, unsupported_claims, verified_context

router = APIRouter(prefix="/applications", tags=["applications"])

_EDITABLE_STATES = {"pending_approval", "approved", "preparing", "ready_to_submit", "confirmation_pending", "failed"}


class PrepareRequest(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)


class RejectRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class EditApplicationRequest(BaseModel):
    answers: dict[str, str] | None = None
    cv_text: str | None = Field(default=None, min_length=1)
    cover_letter_text: str | None = Field(default=None, min_length=1)


def _owned(application_id: str, user: User, db: Session) -> Application:
    application = db.scalar(select(Application).where(Application.id == application_id, Application.user_id == user.id))
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


def _review_payload(
    db: Session,
    user: User,
    application: Application,
    *,
    include_audit: bool = False,
    opportunity: Opportunity | None = None,
    match: JobMatch | None = None,
    cv_gen: GeneratedDocument | None = None,
    cover_gen: GeneratedDocument | None = None,
    answers: dict[str, str] | None = None,
    prefetched: bool = False,
) -> dict[str, Any]:
    if not prefetched:
        opportunity = db.get(Opportunity, application.opportunity_id)
        match = db.scalar(select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.opportunity_id == application.opportunity_id))
        cv_gen, _ = _latest_generated_doc(db, user.id, application.opportunity_id, "cv")
        cover_gen, _ = _latest_generated_doc(db, user.id, application.opportunity_id, "cover_letter")
        answers = {
            row.question_key: row.answer
            for row in db.scalars(select(ApplicationAnswer).where(ApplicationAnswer.application_id == application.id))
        }
    answers = answers or {}
    analysis: dict[str, Any] = {}
    if match and match.analysis_json:
        try:
            analysis = json.loads(match.analysis_json)
        except json.JSONDecodeError:
            analysis = {}
    eligibility_warnings: list[str] = list(analysis.get("risk_warnings", []))
    if match and not match.eligible:
        eligibility_warnings.append("Candidate eligibility check failed for this opportunity.")
    if not application.source_permits_automation:
        eligibility_warnings.append("Source does not permit automated submission.")
    if not application.sensitive_declarations_verified:
        eligibility_warnings.append("Sensitive or legal declarations require verified confirmation.")
    payload: dict[str, Any] = {
        "id": application.id,
        "opportunity_id": application.opportunity_id,
        "status": application.status,
        "application_url": application.application_url,
        "title": opportunity.title if opportunity else None,
        "company": opportunity.company if opportunity else None,
        "job": {
            "id": opportunity.id,
            "title": opportunity.title,
            "company": opportunity.company,
            "location": opportunity.location,
            "url": opportunity.url,
            "description": opportunity.description,
            "deadline": opportunity.deadline,
            "salary_text": opportunity.salary_text,
            "remote_only": opportunity.remote_only,
        } if opportunity else None,
        "match_score": match.score if match else None,
        "match_explanation": match.explanation if match else None,
        "missing_qualifications": analysis.get("missing_skills", []),
        "eligibility_warnings": eligibility_warnings,
        "match": {
            "score": match.score,
            "eligible": match.eligible,
            "explanation": match.explanation,
            "risk_level": match.risk_level,
            "next_action": match.next_action,
            "missing_skills": analysis.get("missing_skills", []),
            "risk_warnings": analysis.get("risk_warnings", []),
        } if match else None,
        "cv_document_id": cv_gen.id if cv_gen else None,
        "cv_preview": cv_gen.editable_text if cv_gen else None,
        "cover_letter_document_id": cover_gen.id if cover_gen else None,
        "cover_letter_preview": cover_gen.editable_text if cover_gen else None,
        "answers": answers,
        "confirmation_reference": application.confirmation_reference,
        "last_error": application.last_error,
        "requires_manual_intervention": application.requires_manual_intervention,
        "source_permits_automation": application.source_permits_automation,
        "required_documents_verified": application.required_documents_verified,
        "required_answers_verified": application.required_answers_verified,
        "sensitive_declarations_verified": application.sensitive_declarations_verified,
        "prepared_at": application.prepared_at,
        "submitted_at": application.submitted_at,
    }
    if include_audit:
        attempts = [
            {"attempt_number": a.attempt_number, "status": a.status, "error_message": a.error_message, "created_at": a.created_at}
            for a in db.scalars(select(ApplicationAttempt).where(ApplicationAttempt.application_id == application.id).order_by(ApplicationAttempt.attempt_number.asc()))
        ]
        audit_logs = [
            {"action": log.action, "details": json.loads(log.details or "{}"), "created_at": log.created_at}
            for log in db.scalars(select(AuditLog).where(AuditLog.resource_type == "application", AuditLog.resource_id == application.id).order_by(AuditLog.created_at.desc()))
        ]
        payload["attempts"] = attempts
        payload["audit_logs"] = audit_logs
    return payload


def _update_generated_text(db: Session, user: User, opportunity: Opportunity | None, generated: GeneratedDocument | None, new_text: str) -> None:
    if generated is None or opportunity is None:
        raise HTTPException(status_code=404, detail="Generated document not found for application")
    context = verified_context(db, user, opportunity, [])
    if unsupported_claims(new_text, context):
        raise HTTPException(status_code=422, detail="Edited document contains unsupported claims")
    document = db.get(Document, generated.document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Backing document not found")
    path = Path(settings.document_storage_dir).resolve() / user.id / document.storage_key
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_file(new_text, generated.file_format, path)
    generated.editable_text = new_text
    document.extracted_text = new_text
    document.content_hash = hashlib.sha256(new_text.encode()).hexdigest()
    document.size_bytes = path.stat().st_size


def _batch_review_payloads(db: Session, user: User, apps: list[Application]) -> list[dict[str, Any]]:
    if not apps:
        return []
    opp_ids = list({app.opportunity_id for app in apps})
    app_ids = [app.id for app in apps]
    opps = {opp.id: opp for opp in db.scalars(select(Opportunity).where(Opportunity.id.in_(opp_ids)))}
    matches = {
        m.opportunity_id: m
        for m in db.scalars(select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.opportunity_id.in_(opp_ids)))
    }
    docs_by_opp_type: dict[tuple[str, str], GeneratedDocument] = {}
    for g in db.scalars(
        select(GeneratedDocument)
        .where(
            GeneratedDocument.user_id == user.id,
            GeneratedDocument.opportunity_id.in_(opp_ids),
            GeneratedDocument.document_type.in_(["cv", "cover_letter"]),
        )
        .order_by(GeneratedDocument.version.desc(), GeneratedDocument.created_at.desc())
    ):
        key = (g.opportunity_id, g.document_type)
        if key not in docs_by_opp_type or (docs_by_opp_type[key].file_format != "pdf" and g.file_format == "pdf"):
            docs_by_opp_type[key] = g
    answers_by_app: dict[str, dict[str, str]] = {}
    for row in db.scalars(select(ApplicationAnswer).where(ApplicationAnswer.application_id.in_(app_ids))):
        answers_by_app.setdefault(row.application_id, {})[row.question_key] = row.answer

    return [
        _review_payload(
            db,
            user,
            app,
            opportunity=opps.get(app.opportunity_id),
            match=matches.get(app.opportunity_id),
            cv_gen=docs_by_opp_type.get((app.opportunity_id, "cv")),
            cover_gen=docs_by_opp_type.get((app.opportunity_id, "cover_letter")),
            answers=answers_by_app.get(app.id, {}),
            prefetched=True,
        )
        for app in apps
    ]


@router.get("")
def list_applications(
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(Application).where(Application.user_id == user.id)
    count_stmt = select(func.count(Application.id)).where(Application.user_id == user.id)
    if status:
        stmt = stmt.where(Application.status == status)
        count_stmt = count_stmt.where(Application.status == status)
    total = int(db.scalar(count_stmt) or 0)
    total_pages = max(1, (total + page_size - 1) // page_size)
    apps = list(
        db.scalars(
            stmt.order_by(Application.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    items = _batch_review_payloads(db, user, apps)
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "counts": count_application_statuses(db, user.id),
    }


@router.post("/opportunities/{opportunity_id}/prepare")
def prepare(opportunity_id: str, payload: PrepareRequest, user: User = Depends(get_current_user), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    opportunity = db.get(Opportunity, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    application = prepare_application(db, user, opportunity, payload.answers)
    return {
        "id": application.id,
        "status": application.status,
        "application_url": application.application_url,
        "required_documents_verified": application.required_documents_verified,
        "required_answers_verified": application.required_answers_verified,
        "sensitive_declarations_verified": application.sensitive_declarations_verified,
    }


@router.get("/queue")
def approval_queue(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    apps = list(
        db.scalars(
            select(Application)
            .where(Application.user_id == user.id, Application.status == "pending_approval")
            .order_by(Application.created_at.desc())
        )
    )
    return _batch_review_payloads(db, user, apps)


@router.put("/{application_id}")
def edit_before_submission(
    application_id: str,
    payload: EditApplicationRequest,
    user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    application = _owned(application_id, user, db)
    if application.status not in _EDITABLE_STATES:
        raise HTTPException(status_code=409, detail=f"Application cannot be edited in status '{application.status}'")
    opportunity = db.get(Opportunity, application.opportunity_id)
    if payload.answers is not None:
        for question, answer in payload.answers.items():
            existing = db.scalar(select(ApplicationAnswer).where(ApplicationAnswer.application_id == application.id, ApplicationAnswer.question_key == question))
            if existing is None:
                db.add(ApplicationAnswer(application_id=application.id, question_key=question, answer=answer))
            else:
                existing.answer = answer
        db.flush()
    if payload.cv_text is not None:
        cv_gen, _ = _latest_generated_doc(db, user.id, application.opportunity_id, "cv")
        _update_generated_text(db, user, opportunity, cv_gen, payload.cv_text)
    if payload.cover_letter_text is not None:
        cover_gen, _ = _latest_generated_doc(db, user.id, application.opportunity_id, "cover_letter")
        _update_generated_text(db, user, opportunity, cover_gen, payload.cover_letter_text)

    check = preflight(db, application)
    application.required_documents_verified = check["required_documents"]
    application.required_answers_verified = check["required_answers"]
    application.sensitive_declarations_verified = check["sensitive_declarations"]
    _record_audit(db, user.id, "application_edited", application.id, {"updated_answers": payload.answers is not None, "updated_cv": payload.cv_text is not None, "updated_cover_letter": payload.cover_letter_text is not None})
    db.commit()
    return _review_payload(db, user, application)


@router.post("/{application_id}/approve")
def approve(application_id: str, user: User = Depends(get_current_user), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> dict[str, str]:
    application = _owned(application_id, user, db)
    if application.status != "pending_approval":
        raise HTTPException(status_code=409, detail="Application is not pending approval")
    application.status = "approved"
    request = db.scalar(select(ApprovalRequest).where(ApprovalRequest.application_id == application.id, ApprovalRequest.status == "pending"))
    if request:
        request.status = "approved"
        request.reviewed_by = user.id
        request.reviewed_at = now()
    _record_audit(db, user.id, "application_approved", application.id, {"reviewed_by": user.id})
    db.commit()
    return {"status": application.status}


@router.post("/{application_id}/reject")
def reject(application_id: str, payload: RejectRequest, user: User = Depends(get_current_user), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> dict[str, str]:
    application = _owned(application_id, user, db)
    if application.status == "submitted":
        raise HTTPException(status_code=409, detail="Submitted application cannot be rejected")
    application.status = "rejected"
    application.last_error = payload.reason
    request = db.scalar(select(ApprovalRequest).where(ApprovalRequest.application_id == application.id, ApprovalRequest.status == "pending"))
    if request:
        request.status = "rejected"
        request.reviewed_by = user.id
        request.reviewed_at = now()
    _record_audit(db, user.id, "application_rejected", application.id, {"reason": payload.reason})
    db.commit()
    return {"status": application.status}


@router.post("/{application_id}/withdraw")
def withdraw(application_id: str, user: User = Depends(get_current_user), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> dict[str, str]:
    application = _owned(application_id, user, db)
    if application.status == "withdrawn":
        return {"status": application.status}
    application.status = "withdrawn"
    _record_audit(db, user.id, "application_withdrawn", application.id, {})
    db.commit()
    return {"status": application.status}


@router.post("/{application_id}/submit")
def submit(application_id: str, user: User = Depends(get_current_user), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    application = _owned(application_id, user, db)
    adapter = None
    try:
        adapter = PlaywrightBrowserAdapter(Path(settings.document_storage_dir) / user.id / "audit")
        application = submit_application(db, application, adapter)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        if adapter and hasattr(adapter, "close"):
            adapter.close()
    return {
        "id": application.id,
        "status": application.status,
        "confirmation_reference": application.confirmation_reference,
        "last_error": application.last_error,
        "requires_manual_intervention": application.requires_manual_intervention,
    }


@router.get("/{application_id}")
def get_application(application_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    application = _owned(application_id, user, db)
    return _review_payload(db, user, application, include_audit=True)
