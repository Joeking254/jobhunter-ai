from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_csrf
from app.core.config import settings
from app.models.models import (
    Application,
    ApprovalRequest,
    AuditLog,
    Notification,
    NotificationDeliveryLog,
    Opportunity,
    User,
    UserSettings,
)
from app.services.application.engine import now as utcnow_app, prepare_application
from app.services.notifications.service import (
    get_notification_settings,
    retry_failed_notifications,
    update_notification_settings,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationSettingsUpdate(BaseModel):
    telegram_enabled: bool | None = None
    telegram_chat_id: str | None = Field(default=None, max_length=120)
    email_notifications_enabled: bool | None = None
    notification_frequency: str | None = None
    min_notification_match_score: int | None = Field(default=None, ge=0, le=100)
    categories: dict[str, dict[str, bool]] | None = None


class TelegramCallbackRequest(BaseModel):
    chat_id: str = Field(min_length=1, max_length=120)
    callback_data: str = Field(min_length=1, max_length=255)


@router.get("")
def list_notifications(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return [
        {"id": row.id, "title": row.title, "body": row.body, "read_at": row.read_at, "created_at": row.created_at}
        for row in rows
    ]


@router.post("/{notification_id}/read")
def mark_read(notification_id: str, user: User = Depends(get_current_user), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> dict[str, str]:
    row = db.scalar(select(Notification).where(Notification.id == notification_id, Notification.user_id == user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    if row.read_at is None:
        row.read_at = utcnow_app()
        db.commit()
    return {"status": "read"}


@router.get("/settings")
def read_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    return get_notification_settings(db, user)


@router.put("/settings")
def write_settings(
    payload: NotificationSettingsUpdate,
    user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return update_notification_settings(
            db,
            user,
            telegram_enabled=payload.telegram_enabled,
            telegram_chat_id=payload.telegram_chat_id,
            email_notifications_enabled=payload.email_notifications_enabled,
            notification_frequency=payload.notification_frequency,
            min_notification_match_score=payload.min_notification_match_score,
            categories=payload.categories,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/deliveries")
def list_deliveries(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(NotificationDeliveryLog)
        .where(NotificationDeliveryLog.user_id == user.id)
        .order_by(NotificationDeliveryLog.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return [
        {
            "id": row.id,
            "channel": row.channel,
            "event_type": row.event_type,
            "status": row.status,
            "attempts": row.attempts,
            "max_attempts": row.max_attempts,
            "last_error": row.last_error,
            "provider_message_id": row.provider_message_id,
            "next_retry_at": row.next_retry_at,
            "sent_at": row.sent_at,
        }
        for row in rows
    ]


@router.post("/retry")
def retry_deliveries(user: User = Depends(get_current_user), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> dict[str, int]:
    retried = retry_failed_notifications(db, user_id=user.id, force=True)
    return {"retried": len(retried), "sent": sum(1 for item in retried if item.status == "sent")}


@router.post("/telegram/callback")
def telegram_callback(
    payload: TelegramCallbackRequest,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if settings.telegram_webhook_secret and x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
        raise HTTPException(status_code=403, detail="Invalid Telegram webhook secret")

    user_settings = db.scalar(
        select(UserSettings).where(
            UserSettings.telegram_chat_id == payload.chat_id,
            UserSettings.telegram_enabled.is_(True),
        )
    )
    if user_settings is None:
        raise HTTPException(status_code=404, detail="Telegram chat is not linked or enabled")
    user = db.get(User, user_settings.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=404, detail="User not found")

    action, _, target_id = payload.callback_data.partition(":")
    if action in {"approve", "reject"}:
        application = db.scalar(select(Application).where(Application.id == target_id, Application.user_id == user.id))
        if application is None:
            raise HTTPException(status_code=404, detail="Application not found")
        if action == "approve":
            if application.status != "pending_approval":
                raise HTTPException(status_code=409, detail="Application is not pending approval")
            application.status = "approved"
        else:
            if application.status == "submitted":
                raise HTTPException(status_code=409, detail="Submitted application cannot be rejected")
            application.status = "rejected"
            application.last_error = "Rejected via Telegram inline action"
        req = db.scalar(select(ApprovalRequest).where(ApprovalRequest.application_id == application.id, ApprovalRequest.status == "pending"))
        if req:
            req.status = "approved" if action == "approve" else "rejected"
            req.reviewed_by = user.id
            req.reviewed_at = utcnow_app()
        db.add(AuditLog(user_id=user.id, action=f"telegram_{action}", resource_type="application", resource_id=application.id))
        db.commit()
        return {"status": application.status}

    if action == "prepare":
        opportunity = db.get(Opportunity, target_id)
        if opportunity is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        application = prepare_application(db, user, opportunity)
        return {"status": application.status, "application_id": application.id}

    raise HTTPException(status_code=422, detail="Unsupported Telegram inline action")
