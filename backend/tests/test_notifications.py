import json
from datetime import datetime, timedelta, timezone
import smtplib

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import Base, import_models
from app.models.models import (
    Application,
    Document,
    Interview,
    JobMatch,
    JobSource,
    NotificationDeliveryLog,
    Opportunity,
    User,
    UserSettings,
)
from app.services.notifications.channels import EmailClient, TelegramClient
from app.services.notifications.service import (
    dispatch_event,
    notify_application_outcome,
    notify_approval_required,
    notify_interview_invitation,
    notify_strong_match,
    notify_upcoming_deadlines,
    retry_failed_notifications,
    send_digest_summary,
    update_notification_settings,
)

import_models()


class FakeSMTP:
    def __init__(self, sent_messages, fail_mode=None):
        self.sent_messages = sent_messages
        self.fail_mode = fail_mode
        self.tls_started = False
        self.logged_in = False

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def starttls(self):
        self.tls_started = True

    def login(self, _user, _password):
        if self.fail_mode == "auth":
            raise smtplib.SMTPAuthenticationError(535, b"Authentication failed")
        self.logged_in = True

    def send_message(self, msg):
        if self.fail_mode == "send":
            raise smtplib.SMTPException("SMTP relay temporary failure")
        self.sent_messages.append({"to": msg["To"], "subject": msg["Subject"], "body": msg.get_content()})


def make_telegram_client(captured, *, status_code=200, ok=True):
    def handler(request):
        body = json.loads(request.content.decode())
        captured.append({"url": str(request.url), "payload": body})
        if status_code >= 400:
            return httpx.Response(status_code, json={"ok": False, "description": "Bad gateway"})
        return httpx.Response(200, json={"ok": ok, "result": {"message_id": len(captured)}})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    return TelegramClient(bot_token="123456:TEST-BOT-TOKEN", api_base_url="https://api.telegram.test", http_client=http_client)


def setup_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'notifications.db'}")
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = User(email="notify@example.com", password_hash="hash", first_name="Grace", last_name="Hopper")
    source = JobSource(name="NotifSource", base_url="https://jobs.example", connector_type="rss", config_json="{}")
    db.add_all([user, source])
    db.flush()
    db.add(
        UserSettings(
            user_id=user.id,
            telegram_chat_id="987654321",
            telegram_enabled=True,
            email_notifications_enabled=True,
            notification_frequency="immediate",
            min_notification_match_score=70,
        )
    )
    opp = Opportunity(
        source_id=source.id,
        external_id="n-1",
        dedupe_hash="n-1",
        title="Platform Engineer",
        company="Cloud Co",
        url="https://jobs.example/n-1",
        description="Python cloud role",
        deadline=datetime.now(timezone.utc) + timedelta(hours=12),
    )
    db.add(opp)
    db.flush()
    match = JobMatch(user_id=user.id, opportunity_id=opp.id, score=91, eligible=True, next_action="Apply")
    db.add(match)
    db.flush()
    app_row = Application(user_id=user.id, opportunity_id=opp.id, status="pending_approval", application_url=opp.url)
    db.add(app_row)
    db.flush()
    interview = Interview(application_id=app_row.id, scheduled_at=datetime.now(timezone.utc) + timedelta(days=2), interview_type="Technical", notes="Zoom link in portal")
    db.add(interview)
    db.commit()
    return db, user, opp, match, app_row, interview


def test_telegram_and_smtp_deliveries_and_events(tmp_path):
    db, user, opp, match, app_row, interview = setup_db(tmp_path)
    tg_sent = []
    smtp_sent = []
    tg = make_telegram_client(tg_sent)
    email = EmailClient(host="smtp.test.local", port=587, username="mailer", password="smtp-secret-password", smtp_factory=lambda _h, _p: FakeSMTP(smtp_sent))

    # 1. Strong match (Telegram inline action + Email alert)
    logs = notify_strong_match(db, user, opp, match, telegram_client=tg, email_client=email)
    assert len(logs) == 2
    assert all(log.status == "sent" for log in logs)
    assert tg_sent[-1]["payload"]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"prepare:{opp.id}"
    assert "New Job Alert" in smtp_sent[-1]["subject"]

    # 2. Approval request (Telegram Approve/Reject inline actions + Email approval)
    notify_approval_required(db, user, app_row, opp, match, telegram_client=tg, email_client=email)
    buttons = tg_sent[-1]["payload"]["reply_markup"]["inline_keyboard"][0]
    assert [btn["callback_data"] for btn in buttons] == [f"approve:{app_row.id}", f"reject:{app_row.id}"]
    assert "Approval Needed" in smtp_sent[-1]["subject"]

    # 3. Successful & failed applications
    app_row.status = "submitted"
    app_row.confirmation_reference = "CONF-777"
    app_row.submitted_at = datetime.now(timezone.utc)
    notify_application_outcome(db, user, app_row, opp, telegram_client=tg, email_client=email)
    assert "CONF-777" in tg_sent[-1]["payload"]["text"]
    assert "Submission Confirmation" in smtp_sent[-1]["subject"]

    app_row.status = "failed"
    app_row.last_error = "Validation failed"
    notify_application_outcome(db, user, app_row, opp, telegram_client=tg, email_client=email)
    assert "Application submission failed" in tg_sent[-1]["payload"]["text"]

    # 4. Interview invitation & upcoming deadline & daily/weekly summaries
    notify_interview_invitation(db, user, interview, telegram_client=tg, email_client=email)
    assert "Interview Invitation" in smtp_sent[-1]["subject"]

    # Make application active again for deadline check
    app_row.status = "pending_approval"
    db.commit()
    deadline_count = notify_upcoming_deadlines(db, hours_ahead=48, telegram_client=tg, email_client=email)
    assert deadline_count == 2

    send_digest_summary(db, user, period="daily", telegram_client=tg, email_client=email)
    assert "Daily summary" in tg_sent[-1]["payload"]["text"]
    send_digest_summary(db, user, period="weekly", telegram_client=tg, email_client=email)
    assert "Weekly Report" in smtp_sent[-1]["subject"]


def test_failed_delivery_logging_and_retry_recovery(tmp_path):
    db, user, opp, match, _app, _interview = setup_db(tmp_path)
    tg_calls = []
    smtp_sent = []
    failing_tg = make_telegram_client(tg_calls, status_code=502)
    failing_smtp = EmailClient(host="smtp.test.local", username="u", password="secret-smtp-password", smtp_factory=lambda _h, _p: FakeSMTP(smtp_sent, fail_mode="send"))

    logs = notify_strong_match(db, user, opp, match, telegram_client=failing_tg, email_client=failing_smtp)
    assert len(logs) == 2
    assert all(log.status == "retrying" and log.attempts == 1 for log in logs)
    assert all("secret-smtp-password" not in (log.last_error or "") for log in logs)

    # Now provider recovers; retry succeeds
    working_tg = make_telegram_client(tg_calls, status_code=200)
    working_smtp = EmailClient(host="smtp.test.local", username="u", password="secret-smtp-password", smtp_factory=lambda _h, _p: FakeSMTP(smtp_sent))
    retried = retry_failed_notifications(db, user_id=user.id, force=True, telegram_client=working_tg, email_client=working_smtp)
    assert len(retried) == 2
    assert all(log.status == "sent" and log.attempts == 2 for log in retried)


def test_failed_delivery_exhausts_retries_to_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "notification_max_retries", 2)
    db, user, _opp, _match, _app, _interview = setup_db(tmp_path)
    failing_tg = make_telegram_client([], status_code=500)
    failing_smtp = EmailClient(host="smtp.test.local", username="u", password="p", smtp_factory=lambda _h, _p: FakeSMTP([], fail_mode="auth"))

    logs = dispatch_event(db, user, "application_failed", "Alert", "Body", telegram_client=failing_tg, email_client=failing_smtp)
    assert all(log.status == "retrying" for log in logs)
    retried = retry_failed_notifications(db, user_id=user.id, force=True, telegram_client=failing_tg, email_client=failing_smtp)
    assert all(log.status == "failed" and log.attempts == 2 for log in retried)


def test_deduplication_preferences_and_security_redaction(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "99999:SUPER-SECRET-BOT-TOKEN")
    monkeypatch.setattr(settings, "smtp_password", "SUPER-SECRET-SMTP-PASS")
    db, user, opp, match, _app, _interview = setup_db(tmp_path)

    # Add a CV document whose content must NEVER appear in Telegram messages
    cv_secret_text = "Confidential CV History: Worked at SecretOrg from 2021-2024 with SSN 123-45-6789"
    db.add(Document(user_id=user.id, name="cv.pdf", document_type="cv", storage_key="cv.pdf", extracted_text=cv_secret_text))
    db.commit()

    tg_sent = []
    smtp_sent = []
    tg = make_telegram_client(tg_sent)
    email = EmailClient(host="smtp.test.local", smtp_factory=lambda _h, _p: FakeSMTP(smtp_sent))

    # Duplicate unchanged opportunity alert is suppressed
    first = notify_strong_match(db, user, opp, match, telegram_client=tg, email_client=email)
    second = notify_strong_match(db, user, opp, match, telegram_client=tg, email_client=email)
    assert len(first) == 2
    assert len(second) == 0

    # Changing match score triggers fresh alert
    match.score = 96
    db.commit()
    third = notify_strong_match(db, user, opp, match, telegram_client=tg, email_client=email)
    assert len(third) == 2

    # Security: credentials and CV contents are redacted from Telegram
    dispatch_event(
        db,
        user,
        "application_failed",
        "Error",
        f"token=abc12345 password=my-pass {settings.telegram_bot_token} {cv_secret_text}",
        telegram_client=tg,
        email_client=email,
    )
    tg_text = tg_sent[-1]["payload"]["text"]
    assert "SUPER-SECRET-BOT-TOKEN" not in tg_text
    assert "my-pass" not in tg_text
    assert "abc12345" not in tg_text
    assert "Confidential CV History" not in tg_text
    assert "123-45-6789" not in tg_text

    # Disable email channel + set min score to 95 + weekly frequency
    update_notification_settings(
        db,
        user,
        email_notifications_enabled=False,
        min_notification_match_score=95,
        notification_frequency="weekly",
        categories={"telegram": {"strong_match": False}},
    )
    match.score = 80
    opp.title = "Updated Title"
    db.commit()
    # Filtered out by min_notification_match_score=95
    assert notify_strong_match(db, user, opp, match, telegram_client=tg, email_client=email) == []


def test_notification_settings_and_telegram_callback_api(client):
    reg = client.post("/api/auth/register", json={"email": "tg@example.com", "password": "StrongPassword1", "first_name": "Ada", "last_name": "Lovelace"})
    assert reg.status_code == 201
    csrf = reg.cookies["jobhunter_csrf"]
    headers = {"X-CSRF-Token": csrf}

    # Update notification settings via API
    updated = client.put(
        "/api/notifications/settings",
        headers=headers,
        json={
            "telegram_enabled": True,
            "telegram_chat_id": "chat-42",
            "email_notifications_enabled": True,
            "notification_frequency": "daily",
            "min_notification_match_score": 80,
            "categories": {"telegram": {"weekly_summary": False}},
        },
    )
    assert updated.status_code == 200
    assert updated.json()["telegram_enabled"] is True
    assert updated.json()["notification_frequency"] == "daily"
    assert updated.json()["min_notification_match_score"] == 80
    assert updated.json()["categories"]["telegram"]["weekly_summary"] is False

    # Invalid frequency returns 422
    assert client.put("/api/notifications/settings", headers=headers, json={"notification_frequency": "hourly"}).status_code == 422

    # Create pending application and approve it via Telegram inline callback
    from app.db.session import get_db
    from app.main import app as fastapi_app

    db_gen = fastapi_app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        user = db.scalar(select(User).where(User.email == "tg@example.com"))
        source = JobSource(name="TGSource", base_url="https://tg.example", connector_type="rss", config_json="{}")
        db.add(source)
        db.flush()
        opp = Opportunity(source_id=source.id, external_id="tg-1", dedupe_hash="tg-1", title="AI Engineer", company="Lab", url="https://tg.example/1")
        db.add(opp)
        db.flush()
        app_row = Application(user_id=user.id, opportunity_id=opp.id, status="pending_approval", application_url=opp.url)
        db.add(app_row)
        db.commit()
        app_id = app_row.id
    finally:
        db_gen.close()

    cb = client.post("/api/notifications/telegram/callback", json={"chat_id": "chat-42", "callback_data": f"approve:{app_id}"})
    assert cb.status_code == 200
    assert cb.json()["status"] == "approved"
