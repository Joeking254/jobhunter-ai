from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import (
    Application,
    Document,
    GeneratedDocument,
    Interview,
    JobMatch,
    Notification,
    NotificationDeliveryLog,
    NotificationPreference,
    Opportunity,
    User,
    UserSettings,
)
from app.services.notifications.channels import DeliveryOutcome, EmailClient, TelegramClient, sanitize_notification_text

NOTIFICATION_FREQUENCIES = {"immediate", "daily", "weekly"}
NOTIFICATION_CHANNELS = {"telegram", "email"}
NOTIFICATION_CATEGORIES = (
    "strong_match",
    "approval_required",
    "application_submitted",
    "application_failed",
    "manual_intervention",
    "interview_invitation",
    "upcoming_deadline",
    "daily_summary",
    "weekly_summary",
)
_FREQUENCY_DEFER_CATEGORIES = {"strong_match"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _content_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _user_settings(db: Session, user: User) -> UserSettings:
    row = db.scalar(select(UserSettings).where(UserSettings.user_id == user.id))
    if row is None:
        row = UserSettings(user_id=user.id)
        db.add(row)
        db.flush()
    return row


def _sensitive_cv_snippets(db: Session, user_id: str) -> list[str]:
    snippets: list[str] = []
    for doc in db.scalars(
        select(Document).where(
            Document.user_id == user_id,
            Document.document_type.in_(["cv", "generated_cv", "cover_letter", "generated_cover_letter"]),
        )
    ):
        if doc.extracted_text:
            snippets.append(doc.extracted_text)
    for gen in db.scalars(
        select(GeneratedDocument).where(
            GeneratedDocument.user_id == user_id,
            GeneratedDocument.document_type.in_(["cv", "cover_letter"]),
        )
    ):
        if gen.editable_text:
            snippets.append(gen.editable_text)
    return snippets


def _category_enabled(db: Session, user_id: str, channel: str, event_type: str) -> bool:
    pref = db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.channel == channel,
            NotificationPreference.event_type == event_type,
        )
    )
    return True if pref is None else bool(pref.enabled)


def get_notification_settings(db: Session, user: User) -> dict[str, Any]:
    row = _user_settings(db, user)
    prefs = list(db.scalars(select(NotificationPreference).where(NotificationPreference.user_id == user.id)))
    pref_map = {(p.channel, p.event_type): bool(p.enabled) for p in prefs}
    categories = {
        channel: {event_type: pref_map.get((channel, event_type), True) for event_type in NOTIFICATION_CATEGORIES}
        for channel in sorted(NOTIFICATION_CHANNELS)
    }
    return {
        "telegram_enabled": bool(row.telegram_enabled),
        "telegram_chat_id": row.telegram_chat_id,
        "email_notifications_enabled": bool(row.email_notifications_enabled),
        "notification_frequency": row.notification_frequency,
        "min_notification_match_score": row.min_notification_match_score,
        "categories": categories,
    }


def update_notification_settings(
    db: Session,
    user: User,
    *,
    telegram_enabled: bool | None = None,
    telegram_chat_id: str | None = None,
    email_notifications_enabled: bool | None = None,
    notification_frequency: str | None = None,
    min_notification_match_score: int | None = None,
    categories: dict[str, dict[str, bool]] | None = None,
) -> dict[str, Any]:
    row = _user_settings(db, user)
    if telegram_enabled is not None:
        row.telegram_enabled = telegram_enabled
    if telegram_chat_id is not None:
        row.telegram_chat_id = telegram_chat_id.strip() or None
    if email_notifications_enabled is not None:
        row.email_notifications_enabled = email_notifications_enabled
    if notification_frequency is not None:
        if notification_frequency not in NOTIFICATION_FREQUENCIES:
            raise ValueError(f"Unsupported notification frequency: {notification_frequency}")
        row.notification_frequency = notification_frequency
    if min_notification_match_score is not None:
        if not 0 <= min_notification_match_score <= 100:
            raise ValueError("min_notification_match_score must be between 0 and 100")
        row.min_notification_match_score = min_notification_match_score
    if categories:
        for channel, events in categories.items():
            if channel not in NOTIFICATION_CHANNELS:
                raise ValueError(f"Unsupported notification channel: {channel}")
            for event_type, enabled in events.items():
                if event_type not in NOTIFICATION_CATEGORIES:
                    raise ValueError(f"Unsupported notification category: {event_type}")
                pref = db.scalar(
                    select(NotificationPreference).where(
                        NotificationPreference.user_id == user.id,
                        NotificationPreference.channel == channel,
                        NotificationPreference.event_type == event_type,
                    )
                )
                if pref is None:
                    pref = NotificationPreference(user_id=user.id, channel=channel, event_type=event_type, enabled=bool(enabled))
                    db.add(pref)
                else:
                    pref.enabled = bool(enabled)
    db.commit()
    return get_notification_settings(db, user)


def _already_sent_unchanged(
    db: Session,
    user_id: str,
    channel: str,
    event_type: str,
    dedupe_key: str | None,
    content_hash: str | None,
) -> bool:
    if not dedupe_key or not content_hash:
        return False
    existing = db.scalar(
        select(NotificationDeliveryLog.id).where(
            NotificationDeliveryLog.user_id == user_id,
            NotificationDeliveryLog.channel == channel,
            NotificationDeliveryLog.event_type == event_type,
            NotificationDeliveryLog.dedupe_key == dedupe_key,
            NotificationDeliveryLog.content_hash == content_hash,
            NotificationDeliveryLog.status == "sent",
        )
    )
    return existing is not None


def _deliver_to_channel(
    log: NotificationDeliveryLog,
    *,
    inline_actions: list[list[dict[str, str]]] | None = None,
    telegram_client: TelegramClient | None = None,
    email_client: EmailClient | None = None,
) -> None:
    log.attempts += 1
    if log.channel == "telegram":
        client = telegram_client or TelegramClient()
        outcome: DeliveryOutcome = client.send_message(log.recipient or "", log.payload_preview or "", inline_actions=inline_actions)
    elif log.channel == "email":
        client = email_client or EmailClient()
        outcome = client.send_email(log.recipient or "", log.subject or "JOBHUNTER AI Notification", log.payload_preview or "")
    else:
        outcome = DeliveryOutcome(False, error=f"Unsupported channel: {log.channel}")

    if outcome.delivered:
        log.status = "sent"
        log.provider_message_id = outcome.provider_message_id
        log.sent_at = _utcnow()
        log.last_error = None
        log.next_retry_at = None
    else:
        log.last_error = (outcome.error or "Delivery failed")[:2000]
        if log.attempts < log.max_attempts:
            log.status = "retrying"
            log.next_retry_at = _utcnow() + timedelta(seconds=settings.notification_retry_backoff_seconds * log.attempts)
        else:
            log.status = "failed"
            log.next_retry_at = None


def dispatch_event(
    db: Session,
    user: User,
    event_type: str,
    title: str,
    telegram_text: str,
    *,
    email_subject: str | None = None,
    email_body: str | None = None,
    dedupe_key: str | None = None,
    content_hash: str | None = None,
    match_score: int | None = None,
    inline_actions: list[list[dict[str, str]]] | None = None,
    telegram_client: TelegramClient | None = None,
    email_client: EmailClient | None = None,
    create_in_app: bool = True,
) -> list[NotificationDeliveryLog]:
    user_settings = _user_settings(db, user)
    if match_score is not None and match_score < user_settings.min_notification_match_score:
        return []

    safe_title = sanitize_notification_text(title)
    cv_snippets = _sensitive_cv_snippets(db, user.id)
    safe_telegram = sanitize_notification_text(telegram_text, redact_cv_content=True, sensitive_snippets=cv_snippets)
    safe_email = sanitize_notification_text(email_body or telegram_text)
    safe_subject = sanitize_notification_text(email_subject or title)

    in_app_id: str | None = None
    if create_in_app:
        if dedupe_key and content_hash and _already_sent_unchanged(db, user.id, "telegram", event_type, dedupe_key, content_hash) and _already_sent_unchanged(db, user.id, "email", event_type, dedupe_key, content_hash):
            return []
        notification = Notification(user_id=user.id, title=safe_title[:255], body=safe_telegram)
        db.add(notification)
        db.flush()
        in_app_id = notification.id

    deferred = user_settings.notification_frequency != "immediate" and event_type in _FREQUENCY_DEFER_CATEGORIES
    logs: list[NotificationDeliveryLog] = []

    channels_to_try: list[tuple[str, bool, str | None, str, str]] = [
        ("telegram", bool(user_settings.telegram_enabled and user_settings.telegram_chat_id), user_settings.telegram_chat_id, safe_title, safe_telegram),
        ("email", bool(user_settings.email_notifications_enabled and user.email), user.email, safe_subject, safe_email),
    ]

    for channel, channel_enabled, recipient, subject, body in channels_to_try:
        if not channel_enabled or not _category_enabled(db, user.id, channel, event_type):
            continue
        if _already_sent_unchanged(db, user.id, channel, event_type, dedupe_key, content_hash):
            continue
        log = NotificationDeliveryLog(
            user_id=user.id,
            notification_id=in_app_id,
            channel=channel,
            event_type=event_type,
            dedupe_key=dedupe_key,
            content_hash=content_hash,
            recipient=recipient,
            subject=subject[:255],
            payload_preview=body,
            status="deferred" if deferred else "pending",
            attempts=0,
            max_attempts=settings.notification_max_retries,
        )
        db.add(log)
        db.flush()
        if not deferred:
            _deliver_to_channel(
                log,
                inline_actions=inline_actions if channel == "telegram" else None,
                telegram_client=telegram_client,
                email_client=email_client,
            )
        logs.append(log)

    db.commit()
    return logs


def retry_failed_notifications(
    db: Session,
    *,
    user_id: str | None = None,
    force: bool = False,
    telegram_client: TelegramClient | None = None,
    email_client: EmailClient | None = None,
) -> list[NotificationDeliveryLog]:
    stmt = select(NotificationDeliveryLog).where(
        NotificationDeliveryLog.status.in_(["retrying", "pending"]),
        NotificationDeliveryLog.attempts < NotificationDeliveryLog.max_attempts,
    )
    if user_id:
        stmt = stmt.where(NotificationDeliveryLog.user_id == user_id)
    candidates = list(db.scalars(stmt))
    now = _utcnow()
    retried: list[NotificationDeliveryLog] = []
    for log in candidates:
        if not force and log.next_retry_at is not None and _as_utc(log.next_retry_at) > now:
            continue
        _deliver_to_channel(log, telegram_client=telegram_client, email_client=email_client)
        retried.append(log)
    db.commit()
    return retried


def notify_strong_match(
    db: Session,
    user: User,
    opportunity: Opportunity,
    match: JobMatch,
    *,
    telegram_client: TelegramClient | None = None,
    email_client: EmailClient | None = None,
) -> list[NotificationDeliveryLog]:
    title = f"Strong Job Match ({match.score}%): {opportunity.title} at {opportunity.company}"
    body = (
        f"Job: {opportunity.title}\n"
        f"Company: {opportunity.company}\n"
        f"Location: {opportunity.location or ('Remote' if opportunity.remote_only else 'Unspecified')}\n"
        f"Match Score: {match.score}/100\n"
        f"Next Action: {match.next_action or 'Review'}\n"
        f"URL: {opportunity.url}"
    )
    inline_actions = [[
        {"text": "Prepare Application", "callback_data": f"prepare:{opportunity.id}"},
        {"text": "Open Job", "url": opportunity.url},
    ]] if opportunity.url.startswith(("http://", "https://")) else None
    digest = _content_hash({
        "title": opportunity.title,
        "company": opportunity.company,
        "url": opportunity.url,
        "deadline": str(opportunity.deadline),
        "score": match.score,
    })
    return dispatch_event(
        db,
        user,
        "strong_match",
        title,
        body,
        email_subject=f"New Job Alert ({match.score}%): {opportunity.title} - {opportunity.company}",
        email_body=body,
        dedupe_key=f"opp:{opportunity.id}",
        content_hash=digest,
        match_score=match.score,
        inline_actions=inline_actions,
        telegram_client=telegram_client,
        email_client=email_client,
    )


def notify_approval_required(
    db: Session,
    user: User,
    application: Application,
    opportunity: Opportunity,
    match: JobMatch | None,
    *,
    telegram_client: TelegramClient | None = None,
    email_client: EmailClient | None = None,
) -> list[NotificationDeliveryLog]:
    score_text = f"{match.score}/100" if match else "N/A"
    title = f"Approval Required: {opportunity.title} at {opportunity.company}"
    body = (
        f"Application awaiting approval.\n"
        f"Job: {opportunity.title}\n"
        f"Company: {opportunity.company}\n"
        f"Match Score: {score_text}\n"
        f"Application ID: {application.id}\n"
        f"URL: {opportunity.url}"
    )
    inline_actions = [[
        {"text": "Approve", "callback_data": f"approve:{application.id}"},
        {"text": "Reject", "callback_data": f"reject:{application.id}"},
    ]]
    digest = _content_hash({"app_id": application.id, "status": application.status, "score": score_text})
    return dispatch_event(
        db,
        user,
        "approval_required",
        title,
        body,
        email_subject=f"Application Approval Needed: {opportunity.title} ({opportunity.company})",
        email_body=body,
        dedupe_key=f"approval:{application.id}",
        content_hash=digest,
        inline_actions=inline_actions,
        telegram_client=telegram_client,
        email_client=email_client,
    )


def notify_application_outcome(
    db: Session,
    user: User,
    application: Application,
    opportunity: Opportunity | None,
    *,
    telegram_client: TelegramClient | None = None,
    email_client: EmailClient | None = None,
) -> list[NotificationDeliveryLog]:
    job_label = f"{opportunity.title} at {opportunity.company}" if opportunity else application.id
    if application.status == "submitted":
        event_type = "application_submitted"
        title = f"Application Submitted: {job_label}"
        body = (
            f"Your application for {job_label} was submitted.\n"
            f"Confirmation Reference: {application.confirmation_reference or 'Pending reference'}\n"
            f"Application ID: {application.id}"
        )
        subject = f"Submission Confirmation: {job_label}"
        inline_actions = None
    elif application.requires_manual_intervention or application.status == "confirmation_pending":
        event_type = "manual_intervention"
        title = f"Manual Intervention Required: {job_label}"
        body = (
            f"Application paused for manual intervention.\n"
            f"Job: {job_label}\n"
            f"Reason: {application.last_error or 'Confirmation or manual verification required'}\n"
            f"Application ID: {application.id}"
        )
        subject = f"Action Required: {job_label}"
        inline_actions = [[{"text": "Reject Application", "callback_data": f"reject:{application.id}"}]]
    else:
        event_type = "application_failed"
        title = f"Application Failed: {job_label}"
        body = (
            f"Application submission failed for {job_label}.\n"
            f"Error: {application.last_error or 'Unknown error'}\n"
            f"Application ID: {application.id}"
        )
        subject = f"Application Failed: {job_label}"
        inline_actions = None

    digest = _content_hash({
        "app_id": application.id,
        "status": application.status,
        "ref": application.confirmation_reference,
        "err": application.last_error,
    })
    return dispatch_event(
        db,
        user,
        event_type,
        title,
        body,
        email_subject=subject,
        email_body=body,
        dedupe_key=f"outcome:{application.id}:{application.status}",
        content_hash=digest,
        inline_actions=inline_actions,
        telegram_client=telegram_client,
        email_client=email_client,
    )


def notify_interview_invitation(
    db: Session,
    user: User,
    interview: Interview,
    *,
    telegram_client: TelegramClient | None = None,
    email_client: EmailClient | None = None,
) -> list[NotificationDeliveryLog]:
    application = db.get(Application, interview.application_id)
    opportunity = db.get(Opportunity, application.opportunity_id) if application else None
    job_label = f"{opportunity.title} at {opportunity.company}" if opportunity else interview.application_id
    title = f"Interview Invitation: {job_label}"
    body = (
        f"Interview scheduled for {job_label}.\n"
        f"When: {interview.scheduled_at.isoformat()}\n"
        f"Type: {interview.interview_type or 'Interview'}\n"
        f"Notes: {interview.notes or 'None'}"
    )
    digest = _content_hash({"interview_id": interview.id, "scheduled_at": interview.scheduled_at.isoformat(), "type": interview.interview_type})
    return dispatch_event(
        db,
        user,
        "interview_invitation",
        title,
        body,
        email_subject=title,
        email_body=body,
        dedupe_key=f"interview:{interview.id}",
        content_hash=digest,
        telegram_client=telegram_client,
        email_client=email_client,
    )


def notify_upcoming_deadlines(
    db: Session,
    *,
    hours_ahead: int = 48,
    telegram_client: TelegramClient | None = None,
    email_client: EmailClient | None = None,
) -> int:
    now = _utcnow()
    horizon = now + timedelta(hours=hours_ahead)
    sent_count = 0
    for user in db.scalars(select(User).where(User.is_active.is_(True))):
        user_settings = _user_settings(db, user)
        matches = list(
            db.scalars(
                select(JobMatch).where(
                    JobMatch.user_id == user.id,
                    JobMatch.eligible.is_(True),
                    JobMatch.score >= user_settings.min_notification_match_score,
                )
            )
        )
        for match in matches:
            opportunity = db.get(Opportunity, match.opportunity_id)
            if not opportunity or opportunity.expired_at is not None or opportunity.deadline is None:
                continue
            deadline = _as_utc(opportunity.deadline)
            if not (now <= deadline <= horizon):
                continue
            existing_app = db.scalar(
                select(Application).where(
                    Application.user_id == user.id,
                    Application.opportunity_id == opportunity.id,
                    Application.status.in_(["submitted", "rejected", "withdrawn", "expired"]),
                )
            )
            if existing_app is not None:
                continue
            title = f"Upcoming Deadline: {opportunity.title} at {opportunity.company}"
            body = (
                f"Application deadline approaching.\n"
                f"Job: {opportunity.title}\n"
                f"Company: {opportunity.company}\n"
                f"Deadline: {deadline.isoformat()}\n"
                f"Match Score: {match.score}/100\n"
                f"URL: {opportunity.url}"
            )
            digest = _content_hash({"opp_id": opportunity.id, "deadline": deadline.isoformat()})
            logs = dispatch_event(
                db,
                user,
                "upcoming_deadline",
                title,
                body,
                email_subject=title,
                email_body=body,
                dedupe_key=f"deadline:{opportunity.id}",
                content_hash=digest,
                telegram_client=telegram_client,
                email_client=email_client,
            )
            sent_count += len(logs)
    return sent_count


def send_digest_summary(
    db: Session,
    user: User,
    *,
    period: str = "daily",
    telegram_client: TelegramClient | None = None,
    email_client: EmailClient | None = None,
) -> list[NotificationDeliveryLog]:
    days = 7 if period == "weekly" else 1
    event_type = "weekly_summary" if period == "weekly" else "daily_summary"
    since = _utcnow() - timedelta(days=days)
    matches_count = int(db.scalar(select(func.count(JobMatch.id)).where(JobMatch.user_id == user.id, JobMatch.created_at >= since)) or 0)
    submitted_count = int(db.scalar(select(func.count(Application.id)).where(Application.user_id == user.id, Application.status == "submitted", Application.submitted_at >= since)) or 0)
    pending_count = int(db.scalar(select(func.count(Application.id)).where(Application.user_id == user.id, Application.status == "pending_approval")) or 0)
    failed_count = int(db.scalar(select(func.count(Application.id)).where(Application.user_id == user.id, Application.status == "failed", Application.updated_at >= since)) or 0)
    interviews_count = int(
        db.scalar(
            select(func.count(Interview.id))
            .join(Application, Application.id == Interview.application_id)
            .where(Application.user_id == user.id, Interview.scheduled_at >= _utcnow())
        )
        or 0
    )
    label = "Weekly" if period == "weekly" else "Daily"
    title = f"{label} JobHunter Summary"
    body = (
        f"{label} summary:\n"
        f"- New matches: {matches_count}\n"
        f"- Submitted applications: {submitted_count}\n"
        f"- Pending approval: {pending_count}\n"
        f"- Failed applications: {failed_count}\n"
        f"- Upcoming interviews: {interviews_count}"
    )
    bucket = _utcnow().strftime("%Y-%W" if period == "weekly" else "%Y-%m-%d")
    digest = _content_hash({"bucket": bucket, "m": matches_count, "s": submitted_count, "p": pending_count, "f": failed_count, "i": interviews_count})
    return dispatch_event(
        db,
        user,
        event_type,
        title,
        body,
        email_subject=f"JOBHUNTER AI {label} Report",
        email_body=body,
        dedupe_key=f"summary:{period}:{bucket}",
        content_hash=digest,
        telegram_client=telegram_client,
        email_client=email_client,
    )
