from datetime import datetime, timezone
import inspect
import json
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import (
    Application,
    ApplicationAnswer,
    ApplicationAttempt,
    ApplicationDocument,
    ApprovalRequest,
    AuditLog,
    BotConfig,
    CareerProfile,
    Document,
    GeneratedDocument,
    JobMatch,
    JobSource,
    Opportunity,
    ProfileFact,
    User,
)
from app.services.application.automation import (
    BrowserAdapter,
    FormField,
    missing_required_fields,
)
from app.services.notifications.service import notify_application_outcome, notify_approval_required
from app.worker.control import effective_match_thresholds, is_shutting_down, task_lock

SUBMISSION_STATES = {
    "discovered",
    "analyzing",
    "matched",
    "pending_approval",
    "approved",
    "preparing",
    "ready_to_submit",
    "submitting",
    "submitted",
    "confirmation_pending",
    "failed",
    "rejected",
    "withdrawn",
    "expired",
}

_WORK_AUTH_TERMS = ("authorized", "authorization", "visa", "sponsorship", "citizenship", "work permit")
_LEGAL_DECL_TERMS = ("legal", "declaration", "criminal", "felony", "conviction", "background", "consent", "terms", "agree")


def now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def valid_application_url(url: str | None) -> bool:
    parsed = urlparse(url or "")
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def classify_decision(
    score: int | None,
    eligible: bool,
    strong_threshold: int | None = None,
    approval_threshold: int | None = None,
) -> str:
    """Classify application decision into automatic, approval_required, or rejected."""
    strong = settings.match_strong_threshold if strong_threshold is None else strong_threshold
    approval = settings.match_approval_threshold if approval_threshold is None else approval_threshold
    if score is None or not eligible or score < approval:
        return "rejected"
    if score >= strong:
        return "automatic"
    return "approval_required"


def _source_permits(source: JobSource | None) -> bool:
    if source is None or not source.is_active:
        return False
    try:
        config = json.loads(source.config_json or "{}")
    except json.JSONDecodeError:
        return False
    if config.get("terms_prohibit_automation"):
        return False
    return bool(config.get("automation_permitted", False))


def _required_sensitive_fact_keys(questions: list[str] | dict[str, str]) -> set[str]:
    keys: set[str] = set()
    for question in questions:
        q = question.lower()
        if any(term in q for term in _WORK_AUTH_TERMS):
            keys.add("work_authorization")
        if any(term in q for term in _LEGAL_DECL_TERMS):
            keys.add("legal_declaration")
    return keys


def _sensitive_declarations_verified(db: Session, user_id: str, questions: list[str] | dict[str, str]) -> bool:
    required_keys = _required_sensitive_fact_keys(questions)
    if not required_keys:
        return True
    confirmed = set(
        db.scalars(
            select(ProfileFact.field_key).where(
                ProfileFact.user_id == user_id,
                ProfileFact.field_key.in_(sorted(required_keys)),
                ProfileFact.status == "confirmed",
            )
        )
    )
    return required_keys.issubset(confirmed)


def _latest_generated_doc(db: Session, user_id: str, opportunity_id: str, document_type: str) -> tuple[GeneratedDocument | None, Document | None]:
    candidates = list(
        db.scalars(
            select(GeneratedDocument)
            .where(
                GeneratedDocument.user_id == user_id,
                GeneratedDocument.opportunity_id == opportunity_id,
                GeneratedDocument.document_type == document_type,
            )
            .order_by(GeneratedDocument.version.desc(), GeneratedDocument.created_at.desc())
        )
    )
    if not candidates:
        return None, None
    preferred = next((item for item in candidates if item.file_format == "pdf"), candidates[0])
    doc = db.get(Document, preferred.document_id)
    return preferred, doc


def _checks_pass(check: dict[str, bool], require_strong_match: bool = False) -> bool:
    required = all(value for key, value in check.items() if key not in {"duplicate_application", "strong_match_for_automatic"})
    return required and not check["duplicate_application"] and (not require_strong_match or check["strong_match_for_automatic"])


def _record_audit(db: Session, user_id: str, action: str, application_id: str, details: dict[str, Any]) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            resource_type="application",
            resource_id=application_id,
            details=json.dumps(details, default=str),
        )
    )


def preflight(db: Session, application: Application, answers: dict[str, str] | None = None) -> dict[str, bool]:
    opportunity = db.get(Opportunity, application.opportunity_id)
    source = db.get(JobSource, opportunity.source_id) if opportunity else None
    match = db.scalar(select(JobMatch).where(JobMatch.user_id == application.user_id, JobMatch.opportunity_id == application.opportunity_id))
    _, cv_doc = _latest_generated_doc(db, application.user_id, application.opportunity_id, "cv")
    _, cover_doc = _latest_generated_doc(db, application.user_id, application.opportunity_id, "cover_letter")
    docs_ok = bool(cv_doc and cv_doc.storage_key and cover_doc and cover_doc.storage_key)

    answer_rows = list(db.scalars(select(ApplicationAnswer).where(ApplicationAnswer.application_id == application.id)))
    answer_map = answers if answers is not None else {row.question_key: row.answer for row in answer_rows}
    answers_ok = all(isinstance(value, str) and bool(value.strip()) for value in answer_map.values())
    verified_sensitive = _sensitive_declarations_verified(db, application.user_id, answer_map)

    job_active = bool(opportunity and opportunity.expired_at is None and source is not None and source.is_active)
    deadline_valid = bool(opportunity and (opportunity.deadline is None or _as_utc(opportunity.deadline) >= now()))
    strong_threshold, _approval_threshold = effective_match_thresholds(db)
    strong_eligible = bool(match and match.eligible and match.score >= strong_threshold)

    duplicate = application.status in {"submitted", "submitting", "confirmation_pending"}
    if not duplicate and opportunity is not None:
        other_same_opp = db.scalar(
            select(Application.id).where(
                Application.user_id == application.user_id,
                Application.opportunity_id == application.opportunity_id,
                Application.id != application.id,
                Application.status.in_(["submitted", "submitting", "confirmation_pending"]),
            )
        )
        other_same_dedupe = db.scalar(
            select(Application.id)
            .join(Opportunity, Opportunity.id == Application.opportunity_id)
            .where(
                Application.user_id == application.user_id,
                Application.id != application.id,
                Application.status.in_(["submitted", "submitting", "confirmation_pending"]),
                (Opportunity.dedupe_hash == opportunity.dedupe_hash) | (Application.application_url == opportunity.url),
            )
        )
        duplicate = bool(other_same_opp or other_same_dedupe)

    return {
        "job_active": job_active,
        "deadline_valid": deadline_valid,
        "candidate_eligible": bool(match and match.eligible),
        "application_url_valid": valid_application_url(opportunity.url if opportunity else None),
        "source_permits_automation": _source_permits(source),
        "duplicate_application": duplicate,
        "required_documents": docs_ok,
        "required_answers": answers_ok,
        "sensitive_declarations": verified_sensitive,
        "strong_match_for_automatic": strong_eligible,
    }


def _candidate_profile_answers(db: Session, user: User | None) -> dict[str, str]:
    if user is None:
        return {}
    profile = db.scalar(select(CareerProfile).where(CareerProfile.user_id == user.id))
    values: dict[str, str] = {
        "Email": user.email,
        "First Name": user.first_name,
        "Last Name": user.last_name,
        "Full Name": f"{user.first_name} {user.last_name}".strip(),
    }
    if profile:
        if profile.phone:
            values["Phone"] = profile.phone
        if profile.city:
            values["City"] = profile.city
        if profile.country:
            values["Country"] = profile.country
        if profile.linkedin_url:
            values["LinkedIn"] = profile.linkedin_url
    return values


def prepare_application(db: Session, user: User, opportunity: Opportunity, answers: dict[str, str] | None = None) -> Application:
    match = db.scalar(select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.opportunity_id == opportunity.id))
    application = db.scalar(select(Application).where(Application.user_id == user.id, Application.opportunity_id == opportunity.id))
    if application is not None and application.status in {"submitted", "submitting", "confirmation_pending"}:
        return application
    if application is None:
        application = Application(user_id=user.id, opportunity_id=opportunity.id, application_url=opportunity.url, status="preparing")
        db.add(application)
        db.flush()

    source = db.get(JobSource, opportunity.source_id)
    application.source_permits_automation = _source_permits(source)
    for generated in db.scalars(select(GeneratedDocument).where(GeneratedDocument.user_id == user.id, GeneratedDocument.opportunity_id == opportunity.id)):
        if db.scalar(select(ApplicationDocument.id).where(ApplicationDocument.application_id == application.id, ApplicationDocument.document_id == generated.document_id)) is None:
            db.add(ApplicationDocument(application_id=application.id, document_id=generated.document_id))

    if answers is not None:
        for question, answer in answers.items():
            existing = db.scalar(select(ApplicationAnswer).where(ApplicationAnswer.application_id == application.id, ApplicationAnswer.question_key == question))
            if existing is None:
                db.add(ApplicationAnswer(application_id=application.id, question_key=question, answer=answer))
            else:
                existing.answer = answer
        db.flush()

    check = preflight(db, application)
    application.required_documents_verified = check["required_documents"]
    application.required_answers_verified = check["required_answers"]
    application.sensitive_declarations_verified = check["sensitive_declarations"]
    application.prepared_at = now()

    strong_threshold, approval_threshold = effective_match_thresholds(db)
    decision = classify_decision(match.score if match else None, bool(match and match.eligible), strong_threshold, approval_threshold)
    if not check["job_active"] or not check["deadline_valid"]:
        application.status = "expired"
    elif decision == "rejected":
        application.status = "rejected"
    elif decision == "automatic" and _checks_pass(check, require_strong_match=True):
        application.status = "ready_to_submit"
    else:
        application.status = "pending_approval"
        if db.scalar(select(ApprovalRequest.id).where(ApprovalRequest.application_id == application.id, ApprovalRequest.status == "pending")) is None:
            db.add(ApprovalRequest(user_id=user.id, application_id=application.id, action="submit", status="pending"))

    _record_audit(db, user.id, "application_prepared", application.id, {"status": application.status, "decision": decision, "preflight": check})
    db.commit()

    if application.status == "pending_approval":
        notify_approval_required(db, user, application, opportunity, match)
    return application


def _pause_for_manual_intervention(
    db: Session,
    user: User | None,
    application: Application,
    opportunity: Opportunity | None,
    attempt: ApplicationAttempt,
    reason: str,
    logs: list[str] | None = None,
) -> Application:
    application.status = "confirmation_pending"
    application.requires_manual_intervention = True
    application.last_error = reason[:2000]
    attempt.status = "manual_intervention"
    attempt.error_message = reason[:2000]
    _record_audit(db, application.user_id, "application_manual_intervention", application.id, {"reason": reason, "logs": logs or []})
    db.commit()
    if user is not None:
        notify_application_outcome(db, user, application, opportunity)
    return application


def submit_application(db: Session, application: Application, adapter: BrowserAdapter) -> Application:
    with task_lock(f"application:{application.id}", ttl_seconds=300) as acquired:
        if not acquired:
            raise RuntimeError("Duplicate overlapping submission prevented for this application")
        return _submit_application_locked(db, application, adapter)


def _submit_application_locked(db: Session, application: Application, adapter: BrowserAdapter) -> Application:
    if application.status not in {"approved", "ready_to_submit"}:
        raise ValueError("Application requires approval or all automatic conditions before submission")

    require_strong = application.status == "ready_to_submit"
    check = preflight(db, application)
    opportunity = db.get(Opportunity, application.opportunity_id)
    user = db.get(User, application.user_id)

    if not _checks_pass(check, require_strong_match=require_strong):
        if not check["job_active"] or not check["deadline_valid"]:
            application.status = "expired"
        elif check["candidate_eligible"]:
            application.status = "pending_approval"
            if db.scalar(select(ApprovalRequest.id).where(ApprovalRequest.application_id == application.id, ApprovalRequest.status == "pending")) is None:
                db.add(ApprovalRequest(user_id=application.user_id, application_id=application.id, action="submit", status="pending"))
        else:
            application.status = "rejected"
        application.requires_manual_intervention = not check["sensitive_declarations"]
        application.last_error = "; ".join(key for key, value in check.items() if (not value if key != "duplicate_application" else value))
        _record_audit(db, application.user_id, "application_preflight_blocked", application.id, {"status": application.status, "preflight": check})
        db.commit()
        if application.requires_manual_intervention and user is not None:
            notify_application_outcome(db, user, application, opportunity)
        return application

    application.status = "submitting"
    application.requires_manual_intervention = False
    attempt_number = (
        db.scalar(
            select(ApplicationAttempt.attempt_number)
            .where(ApplicationAttempt.application_id == application.id)
            .order_by(ApplicationAttempt.attempt_number.desc())
            .limit(1)
        )
        or 0
    ) + 1
    attempt = ApplicationAttempt(application_id=application.id, attempt_number=attempt_number, status="started")
    db.add(attempt)
    db.commit()

    try:
        _, cv_doc = _latest_generated_doc(db, application.user_id, application.opportunity_id, "cv")
        _, cover_doc = _latest_generated_doc(db, application.user_id, application.opportunity_id, "cover_letter")
        if cv_doc is None or cover_doc is None:
            raise ValueError("Required generated CV and cover letter are unavailable")

        cv_path = str(Path(settings.document_storage_dir) / application.user_id / cv_doc.storage_key)
        cover_path = str(Path(settings.document_storage_dir) / application.user_id / cover_doc.storage_key)
        detection = adapter.detect_form(application.application_url or "")

        if detection.requires_manual_intervention:
            return _pause_for_manual_intervention(
                db,
                user,
                application,
                opportunity,
                attempt,
                detection.reason or "Manual intervention required",
                detection.logs,
            )

        explicit_answers = {
            row.question_key: row.answer
            for row in db.scalars(select(ApplicationAnswer).where(ApplicationAnswer.application_id == application.id))
        }
        answer_map = {**_candidate_profile_answers(db, user), **explicit_answers}

        field_labels = [f"{f.label} {f.name}" for f in detection.fields]
        if not _sensitive_declarations_verified(db, application.user_id, field_labels):
            return _pause_for_manual_intervention(
                db,
                user,
                application,
                opportunity,
                attempt,
                "Unresolved sensitive or legal declaration on form requires verified profile confirmation",
                detection.logs,
            )

        # For real browser adapters (where attachments exist on disk), enforce required field presence so nothing is fabricated.
        if Path(cv_path).is_file() and Path(cover_path).is_file():
            missing = missing_required_fields(detection.fields, answer_map, cv_path, cover_path)
            if missing:
                return _pause_for_manual_intervention(
                    db,
                    user,
                    application,
                    opportunity,
                    attempt,
                    f"Missing verified answers for required fields: {', '.join(missing)}",
                    detection.logs,
                )

        adapter.fill_form(detection.fields, answer_map, cv_path, cover_path)
        screenshot_name = f"app-{application.id}-attempt-{attempt_number}.png"
        sig = inspect.signature(adapter.submit)
        if "screenshot_name" in sig.parameters:
            result = adapter.submit(screenshot_name=screenshot_name)
        else:
            result = adapter.submit()

        if result.status == "submitted":
            application.status = "submitted"
            ts = now()
            application.submitted_at = ts
            application.applied_at = ts
        elif result.status == "failed":
            application.status = "failed"
            application.submitted_at = None
        else:
            application.status = "confirmation_pending"
            application.submitted_at = None

        application.confirmation_reference = result.confirmation_reference
        application.last_error = result.error
        attempt.status = result.status
        attempt.error_message = result.error
        _record_audit(
            db,
            application.user_id,
            "application_submission_attempt",
            application.id,
            {
                "attempt_number": attempt_number,
                "status": application.status,
                "confirmation_reference": result.confirmation_reference,
                "screenshot_path": result.screenshot_path,
                "error": result.error,
                "logs": result.logs,
            },
        )
        db.commit()
        if user is not None:
            notify_application_outcome(db, user, application, opportunity)
    except BaseException as exc:
        application.status = "failed"
        application.last_error = f"Submission interrupted: {exc}"[:2000] if isinstance(exc, (KeyboardInterrupt, SystemExit)) else str(exc)[:2000]
        attempt.status = "failed"
        attempt.error_message = application.last_error
        _record_audit(db, application.user_id, "application_submission_error", application.id, {"attempt_number": attempt_number, "error": application.last_error})
        db.commit()
        if user is not None:
            notify_application_outcome(db, user, application, opportunity)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
    return application


def count_application_statuses(db: Session, user_id: str) -> dict[str, int]:
    rows = db.execute(
        select(Application.status, func.count(Application.id))
        .where(Application.user_id == user_id)
        .group_by(Application.status)
    ).all()
    counts = {status: int(count) for status, count in rows}
    submitted = counts.get("submitted", 0)
    prepared_not_submitted = sum(
        counts.get(state, 0)
        for state in ("preparing", "pending_approval", "approved", "ready_to_submit", "confirmation_pending")
    )
    return {
        "total": sum(counts.values()),
        "submitted": submitted,
        "prepared_not_submitted": prepared_not_submitted,
        "by_status": counts,
    }


def run_automatic_submissions(db: Session, adapter_factory: Callable[[str], BrowserAdapter]) -> list[Application]:
    cfg = db.scalar(select(BotConfig).where(BotConfig.scope_key == "global"))
    if cfg and (cfg.bot_paused or cfg.auto_apply_paused):
        return []
    ready_apps = list(db.scalars(select(Application).where(Application.status == "ready_to_submit")))
    processed: list[Application] = []
    for application in ready_apps:
        if is_shutting_down():
            break
        adapter = adapter_factory(application.user_id)
        try:
            processed.append(submit_application(db, application, adapter))
        except RuntimeError:
            # Duplicate/locked submission skipped safely
            continue
        finally:
            if hasattr(adapter, "close"):
                adapter.close()
    return processed
