from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import smtplib
from types import SimpleNamespace

import httpx
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from reportlab.pdfgen import canvas
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.db.session import get_db
from app.main import app as fastapi_app
from app.models.models import (
    AIProcessingHistory,
    Application,
    ApplicationAttempt,
    ApprovalRequest,
    BotRun,
    JobMatch,
    JobSource,
    NotificationDeliveryLog,
    Opportunity,
    User,
)
from app.services.ai.analysis import analyze_opportunity
from app.services.ai.matching import match_opportunity
from app.services.application.automation import PlaywrightBrowserAdapter, get_browser_semaphore
from app.services.application.engine import prepare_application, submit_application
from app.services.discovery import runner as discovery_runner
from app.services.discovery.connectors import RSSConnector
from app.services.discovery.runner import run_source
from app.services.generation.service import generate_documents
from app.services.monitoring import collect_monitoring_summary
from app.services.notifications.channels import EmailClient, TelegramClient
from app.services.notifications.service import notify_application_outcome, notify_approval_required
from app.worker.control import DistributedTaskLock, recover_interrupted_applications
from tests.test_applications import make_fake_playwright_factory


def _make_pdf() -> bytes:
    stream = BytesIO()
    pdf = canvas.Canvas(stream)
    pdf.drawString(72, 720, "Ada Lovelace Verified CV Python FastAPI")
    pdf.save()
    return stream.getvalue()


def test_complete_21_step_end_to_end_workflow(client, tmp_path, monkeypatch):
    # 1. Create administrator account (first registered user becomes admin)
    reg = client.post(
        "/api/auth/register",
        json={"email": "admin@jobs.jkdesignke.com", "password": "StrongAdminPassword1", "first_name": "Ada", "last_name": "Lovelace"},
    )
    assert reg.status_code == 201
    assert reg.json()["is_admin"] is True
    headers = {"X-CSRF-Token": reg.cookies["jobhunter_csrf"]}

    # 2. Complete career profile
    assert client.put(
        "/api/profile",
        headers=headers,
        json={"phone": "+254700000000", "city": "Nairobi", "country": "Kenya", "professional_summary": "Senior Python engineer"},
    ).status_code == 200
    assert client.post("/api/profile/skills", headers=headers, json={"name": "Python", "category": "programming", "years_experience": 5}).status_code == 201
    assert client.post("/api/profile/skills", headers=headers, json={"name": "SQL", "category": "technical", "years_experience": 4}).status_code == 201
    assert client.post("/api/profile/education", headers=headers, json={"institution": "University", "qualification": "BSc", "field_of_study": "Computer Science"}).status_code == 201
    assert client.post("/api/profile/experience", headers=headers, json={"company": "Analytical Co", "title": "Software Engineer"}).status_code == 201

    # 3. Upload CV
    up = client.post(
        "/api/documents",
        headers=headers,
        data={"category": "cv", "is_default": "true"},
        files={"file": ("ada_cv.pdf", _make_pdf(), "application/pdf")},
    )
    assert up.status_code == 201

    # 4. Configure AI provider & preferences
    assert client.put(
        "/api/dashboard/ai-config",
        headers=headers,
        json={"preferred_locations": "Nairobi, Remote", "remote_only": False, "career_preferences": "Software Engineer"},
    ).status_code == 200
    assert client.put("/api/bot/config", headers=headers, json={"search_frequency_minutes": 360, "match_strong_threshold": 85, "match_approval_threshold": 65}).status_code == 200

    # 5 & 6. Configure Telegram & Email notifications
    notif_cfg = client.put(
        "/api/notifications/settings",
        headers=headers,
        json={"telegram_enabled": True, "telegram_chat_id": "100200300", "email_notifications_enabled": True, "notification_frequency": "immediate", "min_notification_match_score": 65},
    )
    assert notif_cfg.status_code == 200

    # 7. Enable job source
    src_res = client.post(
        "/api/sources",
        headers=headers,
        json={
            "name": "TrustedRSS",
            "base_url": "https://trusted.jobs.test",
            "connector_type": "rss",
            "config": {"feed_url": "https://trusted.jobs.test/feed.xml", "company": "Trusted Co", "automation_permitted": True, "rate_limit_seconds": 0},
        },
    )
    assert src_res.status_code == 200
    source_id = src_res.json()["id"]

    # 8, 9, 10. Run discovery with duplicate entry, store opportunities, detect duplicates
    rss_xml = """<rss><channel>
      <item><guid>job-1</guid><title>Software Engineer</title><link>https://trusted.jobs.test/apply/1</link><description>Python SQL Software role in Nairobi</description><location>Nairobi</location></item>
      <item><guid>job-1</guid><title>Software Engineer</title><link>https://trusted.jobs.test/apply/1</link><description>Python SQL Software role in Nairobi</description><location>Nairobi</location></item>
      <item><guid>job-2</guid><title>Machine Learning Engineer</title><link>https://trusted.jobs.test/apply/2</link><description>Python Kubernetes Deep Learning 5 years</description><location>Nairobi</location></item>
    </channel></rss>"""

    class MockRSS(RSSConnector):
        def __init__(self, config):
            super().__init__(config, httpx.Client(transport=httpx.MockTransport(lambda _req: httpx.Response(200, text=rss_xml))))

    monkeypatch.setitem(discovery_runner.CONNECTOR_TYPES, "rss", MockRSS)

    db_gen = fastapi_app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        user = db.scalar(select(User).where(User.email == "admin@jobs.jkdesignke.com"))
        source = db.get(JobSource, source_id)
        hist = run_source(db, source)
        assert hist.status == "success"
        assert hist.created_count == 2  # Duplicate skipped

        # 11 & 12. Analyze job descriptions (with cache verification) & calculate matching scores
        opps = list(db.scalars(select(Opportunity).order_by(Opportunity.external_id.asc())))
        assert len(opps) == 2
        opp1, opp2 = opps[0], opps[1]
        analysis1 = analyze_opportunity(db, opp1)
        assert "python" in analysis1["required_skills"]
        before_cache = db.scalar(select(func.count(AIProcessingHistory.id)))
        analyze_opportunity(db, opp1)
        assert db.scalar(select(func.count(AIProcessingHistory.id))) == before_cache

        m1 = match_opportunity(db, user, opp1)
        m2 = match_opportunity(db, user, opp2)
        assert m1["match_score"] >= 85
        assert m2["match_score"] < 85

        # Force opp1 into approval tier for full approval -> submit workflow test
        match_row = db.scalar(select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.opportunity_id == opp1.id))
        match_row.score = 78
        db.commit()

        # 13 & 14. Generate tailored CV & cover letter
        gen_res = client.post(f"/api/generation/opportunities/{opp1.id}", headers=headers, json={"formats": ["pdf"], "questions": ["Why Trusted Co?"]})
        assert gen_res.status_code == 200
        assert {"cv", "cover_letter", "application_answers"}.issubset({item["document_type"] for item in gen_res.json()})

        # 15. Create approval request
        prep_res = client.post(
            f"/api/applications/opportunities/{opp1.id}/prepare",
            headers=headers,
            json={"answers": {"Why Trusted Co?": "Aligned with Python backend engineering."}},
        )
        assert prep_res.status_code == 200
        assert prep_res.json()["status"] == "pending_approval"
        app_id = prep_res.json()["id"]
        assert db.scalar(select(ApprovalRequest.id).where(ApprovalRequest.application_id == app_id)) is not None

        # 16. Approve application
        assert client.post(f"/api/applications/{app_id}/approve", headers=headers).json()["status"] == "approved"

        # 17 & 18. Complete permitted test application & verify submission
        form_html = """<html><body><form>
          <input name="email" aria-label="Email" required />
          <textarea name="why" aria-label="Why Trusted Co?" required></textarea>
          <input type="file" name="cv_file" aria-label="CV" required />
          <input type="file" name="cover_file" aria-label="Cover Letter" required />
          <button type="submit">Submit</button>
        </form></body></html>"""

        def on_submit(page):
            page.html = "<html><body><p>Application submitted! Confirmation ID: E2E-2026-01</p></body></html>"

        factory, _fake_page = make_fake_playwright_factory({"https://trusted.jobs.test/apply/1": form_html}, on_submit)
        adapter = PlaywrightBrowserAdapter(tmp_path / "audit", playwright_factory=factory)
        app_row = db.get(Application, app_id)
        submitted = submit_application(db, app_row, adapter)
        adapter.close()
        assert submitted.status == "submitted"
        assert submitted.confirmation_reference == "E2E-2026-01"

        # 19. Save & verify application history
        hist_res = client.get("/api/applications")
        assert hist_res.status_code == 200
        assert hist_res.json()["counts"]["submitted"] == 1
        assert hist_res.json()["items"][0]["confirmation_reference"] == "E2E-2026-01"

        # 20. Send notifications (Telegram + SMTP test doubles)
        tg_sent = []
        smtp_sent = []
        tg = TelegramClient("test-token", "https://api.telegram.test", httpx.Client(transport=httpx.MockTransport(lambda req: (tg_sent.append(req), httpx.Response(200, json={"ok": True, "result": {"message_id": 1}}))[1])))

        class FakeSMTP:
            def __enter__(self): return self
            def __exit__(self, *_a): return False
            def starttls(self): pass
            def login(self, *_a): pass
            def send_message(self, msg): smtp_sent.append(msg)

        email = EmailClient(host="smtp.test", username="u", password="p", smtp_factory=lambda _h, _p: FakeSMTP())
        logs = notify_approval_required(db, user, app_row, opp1, match_row, telegram_client=tg, email_client=email)
        assert len(logs) == 2 and all(l.status == "sent" for l in logs)

        # 21. Update dashboard analytics & overview
        ov = client.get("/api/dashboard/overview").json()
        assert ov["total_opportunities"] == 2
        assert ov["applications_submitted"] == 1
        an = client.get("/api/dashboard/analytics").json()
        assert an["interview_conversion"]["submitted"] == 1
        assert len(an["source_performance"]) == 1
    finally:
        db_gen.close()


def test_all_13_failure_scenarios_handled_safely(client, tmp_path, monkeypatch):
    reg = client.post("/api/auth/register", json={"email": "fail@example.com", "password": "StrongPassword1", "first_name": "Ada", "last_name": "Lovelace"})
    assert reg.status_code == 201
    headers = {"X-CSRF-Token": reg.cookies["jobhunter_csrf"]}

    db_gen = fastapi_app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        user = db.scalar(select(User).where(User.email == "fail@example.com"))
        src = JobSource(name="FailSource", base_url="https://fail.test", connector_type="rss", config_json=json.dumps({"automation_permitted": True, "rate_limit_seconds": 0}))
        db.add(src)
        db.flush()
        opp = Opportunity(source_id=src.id, external_id="f-1", dedupe_hash="f-1", title="Python Engineer", company="FailCo", url="https://fail.test/1", description="Python SQL")
        db.add(opp)
        db.flush()

        # 1 & 2. Invalid AI API key (401) and AI provider timeout -> safe fallback without crash
        monkeypatch.setattr(settings, "ai_provider", "openai_compatible")
        monkeypatch.setattr(settings, "ai_api_url", "https://ai.invalid.test/v1/chat")
        monkeypatch.setattr(settings, "ai_api_key", "sk-invalid-secret-key")
        monkeypatch.setattr("httpx.post", lambda *_a, **_kw: httpx.Response(401, request=httpx.Request("POST", "https://ai.invalid.test")))
        res_401 = analyze_opportunity(db, opp)
        assert "python" in res_401["required_skills"]
        failed_ai_log = db.scalar(select(AIProcessingHistory).where(AIProcessingHistory.status == "failed"))
        assert failed_ai_log is not None and "sk-invalid-secret-key" not in (failed_ai_log.output or "")

        opp_t = Opportunity(source_id=src.id, external_id="f-t", dedupe_hash="f-t", title="SQL Engineer", company="FailCo", url="https://fail.test/t", description="SQL role")
        db.add(opp_t)
        db.commit()

        def raise_timeout(*_a, **_kw):
            raise httpx.ReadTimeout("AI timed out")

        monkeypatch.setattr("httpx.post", raise_timeout)
        res_to = analyze_opportunity(db, opp_t)
        assert "sql" in res_to["required_skills"]
        # External generation timeout also falls back safely to verified templates
        assert len(generate_documents(db, user, opp_t, [], ["pdf"])) == 3
        monkeypatch.setattr(settings, "ai_provider", "rules")

        # 3 & 4. Database connection failure & Redis unavailable -> readiness returns 503 & monitoring returns safe error
        from app.api.routes import health as health_mod

        class BrokenEngine:
            def connect(self):
                raise OperationalError("SELECT 1", {}, Exception("DB down"))

        monkeypatch.setattr(health_mod, "engine", BrokenEngine())
        monkeypatch.setattr(health_mod.Redis, "from_url", lambda *_a, **_kw: (_ for _ in ()).throw(RedisConnectionError("Redis down")))
        ready = client.get("/api/health/ready")
        assert ready.status_code == 503
        assert ready.json()["detail"]["checks"] == {"mysql": "error", "redis": "error"}

        class BrokenDB:
            def execute(self, *_a, **_kw):
                raise OperationalError("SELECT 1", {}, Exception("DB down"))

        mon = collect_monitoring_summary(BrokenDB(), redis_factory=lambda: (_ for _ in ()).throw(RedisConnectionError("Redis down")))
        assert mon["services"]["database"]["status"] == "error"
        assert mon["services"]["redis"]["status"] == "error"

        # Lock falls back cleanly when Redis is unavailable
        lock = DistributedTaskLock("redis-down", redis_factory=lambda: (_ for _ in ()).throw(RedisConnectionError("down")))
        assert lock.acquire() is True
        lock.release()

        # 5. Job source unavailable -> SourceExecutionHistory records failure & reliability drops
        class DownRSS(RSSConnector):
            def fetch(self, _q):
                raise RuntimeError("503 Service Unavailable")

        monkeypatch.setitem(discovery_runner.CONNECTOR_TYPES, "rss", DownRSS)
        bad_hist = run_source(db, src)
        assert bad_hist.status == "failed"

        # 6, 7, 8. Expired vacancy, duplicate vacancy, invalid application URL
        exp_opp = Opportunity(source_id=src.id, external_id="exp", dedupe_hash="exp", title="Expired", company="Co", url="ftp://invalid-url", deadline=datetime.now(timezone.utc) - timedelta(days=1))
        db.add(exp_opp)
        db.flush()
        db.add(JobMatch(user_id=user.id, opportunity_id=exp_opp.id, score=95, eligible=True, analysis_json="{}"))
        generate_documents(db, user, exp_opp, [], ["pdf"])
        exp_app = prepare_application(db, user, exp_opp, {"Email": "fail@example.com"})
        assert exp_app.status == "expired"

        # Invalid URL on active match routes to pending_approval instead of ready_to_submit
        bad_url_opp = Opportunity(source_id=src.id, external_id="badurl", dedupe_hash="badurl", title="Engineer", company="Co", url="not-a-url")
        db.add(bad_url_opp)
        db.flush()
        db.add(JobMatch(user_id=user.id, opportunity_id=bad_url_opp.id, score=95, eligible=True, analysis_json="{}"))
        generate_documents(db, user, bad_url_opp, [], ["pdf"])
        bad_url_app = prepare_application(db, user, bad_url_opp, {"Email": "fail@example.com"})
        assert bad_url_app.status == "pending_approval"

        # 9 & 10. Missing required info on live form & CAPTCHA challenge pause without fabrication
        db.add(JobMatch(user_id=user.id, opportunity_id=opp.id, score=95, eligible=True, analysis_json="{}"))
        generate_documents(db, user, opp, [], ["pdf"])
        app_missing = prepare_application(db, user, opp, {"Email": "fail@example.com"})
        assert app_missing.status == "ready_to_submit"

        missing_html = "<html><body><form><input name='portfolio_secret_q' aria-label='Security Clearance Number' required /><button type='submit'>Submit</button></form></body></html>"
        f_miss, _ = make_fake_playwright_factory({"https://fail.test/1": missing_html}, lambda _p: None)
        ad_miss = PlaywrightBrowserAdapter(tmp_path / "m_audit", playwright_factory=f_miss)
        paused_miss = submit_application(db, app_missing, ad_miss)
        ad_miss.close()
        assert paused_miss.status == "confirmation_pending"
        assert paused_miss.requires_manual_intervention is True
        assert "Missing verified answers" in (paused_miss.last_error or "")

        captcha_html = "<html><body><div class='g-recaptcha'></div><form><input name='email' /><button type='submit'>Submit</button></form></body></html>"
        app_missing.status = "approved"
        db.commit()
        f_cap, _ = make_fake_playwright_factory({"https://fail.test/1": captcha_html}, lambda _p: None)
        ad_cap = PlaywrightBrowserAdapter(tmp_path / "c_audit", playwright_factory=f_cap)
        paused_cap = submit_application(db, app_missing, ad_cap)
        ad_cap.close()
        assert paused_cap.status == "confirmation_pending"
        assert "CAPTCHA" in (paused_cap.last_error or "")

        # 11. Failed form submission
        val_html = "<html><body><form><input name='email' aria-label='Email' required /><button type='submit'>Submit</button></form></body></html>"
        app_missing.status = "approved"
        db.commit()
        f_val, _ = make_fake_playwright_factory({"https://fail.test/1": val_html}, lambda p: setattr(p, "html", "<html><body><div class='error'>Invalid phone</div></body></html>"))
        ad_val = PlaywrightBrowserAdapter(tmp_path / "v_audit", playwright_factory=f_val)
        failed_app = submit_application(db, app_missing, ad_val)
        ad_val.close()
        assert failed_app.status == "failed"

        # 12. Notification failure logs retrying without leaking secrets
        failing_smtp = EmailClient(host="smtp.test", username="u", password="secret-smtp-password", smtp_factory=lambda _h, _p: (_ for _ in ()).throw(smtplib.SMTPException("SMTP down secret-smtp-password")))
        n_logs = notify_application_outcome(db, user, failed_app, opp, email_client=failing_smtp)
        assert any(l.status == "retrying" and "secret-smtp-password" not in (l.last_error or "") for l in n_logs)

        # 13. Interrupted worker recovers stranded 'submitting' applications
        failed_app.status = "submitting"
        db.add(ApplicationAttempt(application_id=failed_app.id, attempt_number=99, status="started"))
        db.commit()
        assert recover_interrupted_applications(db) == 1
        db.refresh(failed_app)
        assert failed_app.status == "failed"
    finally:
        db_gen.close()


def test_performance_pagination_and_browser_concurrency_limit(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "browser_max_concurrency", 2)
    sem = get_browser_semaphore()
    f, _ = make_fake_playwright_factory({"https://a.test": "<html></html>"}, lambda _p: None)
    a1 = PlaywrightBrowserAdapter(tmp_path / "b1", playwright_factory=f)
    a2 = PlaywrightBrowserAdapter(tmp_path / "b2", playwright_factory=f)
    # 3rd concurrent browser acquisition must wait / fail when semaphore=2 is saturated
    assert sem.acquire(blocking=False) is False
    a1.close()
    a2.close()

    # Large dataset pagination on /api/opportunities and /api/applications
    reg = client.post("/api/auth/register", json={"email": "perf@example.com", "password": "StrongPassword1", "first_name": "Ada", "last_name": "Lovelace"})
    assert reg.status_code == 201
    db_gen = fastapi_app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        user = db.scalar(select(User).where(User.email == "perf@example.com"))
        src = JobSource(name="PerfBoard", base_url="https://perf.example", connector_type="rss", config_json="{}")
        db.add(src)
        db.flush()
        for idx in range(35):
            opp = Opportunity(source_id=src.id, external_id=f"p-{idx}", dedupe_hash=f"p-{idx}", title=f"Role {idx}", company="PerfCo", url=f"https://perf.example/{idx}")
            db.add(opp)
            db.flush()
            db.add(Application(user_id=user.id, opportunity_id=opp.id, status="preparing", application_url=opp.url))
        db.commit()
    finally:
        db_gen.close()

    opps_p2 = client.get("/api/opportunities?page=2&page_size=10").json()
    assert opps_p2["total"] == 35
    assert opps_p2["total_pages"] == 4
    assert len(opps_p2["items"]) == 10

    apps_p2 = client.get("/api/applications?page=2&page_size=15").json()
    assert apps_p2["total"] == 35
    assert apps_p2["total_pages"] == 3
    assert len(apps_p2["items"]) == 15
