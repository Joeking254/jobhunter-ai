import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from bs4 import BeautifulSoup
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import Base, import_models
from app.models.models import (
    ApprovalRequest,
    AuditLog,
    CareerProfile,
    Document,
    Experience,
    GeneratedDocument,
    JobMatch,
    JobSource,
    Notification,
    Opportunity,
    ProfileFact,
    User,
)
from app.services.application.automation import (
    BrowserAdapter,
    FormDetection,
    FormField,
    PlaywrightBrowserAdapter,
    SubmissionResult,
    identify_field_value,
)
from app.services.application.engine import (
    classify_decision,
    count_application_statuses,
    prepare_application,
    run_automatic_submissions,
    submit_application,
)
from app.services.generation.service import generate_documents

import_models()


class MockBrowser(BrowserAdapter):
    def __init__(self, result=None, manual=False):
        self.result = result or SubmissionResult("submitted", "REF-123")
        self.manual = manual
        self.filled = {}

    def detect_form(self, url):
        return FormDetection(
            [
                FormField("email", "Email", required=True),
                FormField("resume", "CV file", "file"),
                FormField("cover", "Cover letter", "file"),
            ],
            self.manual,
            "CAPTCHA detected" if self.manual else None,
        )

    def fill_form(self, fields, answers, cv_path, cover_letter_path):
        self.filled = {field.name: identify_field_value(field, answers) or "" for field in fields}
        self.filled["cv_path"] = cv_path
        self.filled["cover_path"] = cover_letter_path

    def submit(self):
        return self.result


class _FakeElement:
    def __init__(self, tag, page):
        self.tag = tag
        self.page = page

    def evaluate(self, script):
        if "tagName" in script:
            return self.tag.name
        return None

    def get_attribute(self, attr):
        val = self.tag.get(attr)
        if isinstance(val, list):
            return " ".join(val)
        return val

    def inner_text(self):
        return self.tag.get_text(" ", strip=True)

    def fill(self, value):
        key = self.tag.get("name") or self.tag.get("id")
        self.page.values[key] = value

    def select_option(self, value=None, label=None):
        key = self.tag.get("name") or self.tag.get("id")
        self.page.values[key] = label if label is not None else value

    def check(self):
        key = self.tag.get("name") or self.tag.get("id")
        self.page.values[key] = "checked"

    def uncheck(self):
        key = self.tag.get("name") or self.tag.get("id")
        self.page.values.pop(key, None)

    def set_input_files(self, path):
        key = self.tag.get("name") or self.tag.get("id")
        self.page.files[key] = path

    def click(self):
        self.page.submit_handler(self.page)


class _FakeLocator:
    def __init__(self, selector, page):
        self.selector = selector
        self.page = page

    def _matches(self):
        soup = BeautifulSoup(self.page.html, "html.parser")
        if self.selector == "body":
            body = soup.find("body")
            return [body] if body else [soup]
        return soup.select(self.selector)

    def all(self):
        return [_FakeElement(tag, self.page) for tag in self._matches()]

    def count(self):
        return len(self._matches())

    @property
    def first(self):
        matches = self._matches()
        return _FakeElement(matches[0], self.page)

    def inner_text(self):
        matches = self._matches()
        return matches[0].get_text(" ", strip=True) if matches else ""


class _FakePlaywrightPage:
    def __init__(self, routes, submit_handler):
        self.routes = routes
        self.submit_handler = submit_handler
        self.html = ""
        self.values = {}
        self.files = {}

    def set_default_timeout(self, _ms):
        pass

    def goto(self, url, **_kwargs):
        self.html = self.routes[url]

    def content(self):
        return self.html

    def locator(self, selector):
        return _FakeLocator(selector, self)

    def wait_for_load_state(self, *_args, **_kwargs):
        pass

    def evaluate(self, _script):
        return []

    def screenshot(self, path, **_kwargs):
        Path(path).write_bytes(b"PNG-AUDIT")


def make_fake_playwright_factory(routes, submit_handler):
    page = _FakePlaywrightPage(routes, submit_handler)

    class _Factory:
        def start(self):
            return SimpleNamespace(
                chromium=SimpleNamespace(
                    launch=lambda **_kw: SimpleNamespace(
                        new_context=lambda **_ckw: SimpleNamespace(new_page=lambda: page, close=lambda: None),
                        close=lambda: None,
                    )
                ),
                stop=lambda: None,
            )

    return _Factory, page


def fixture(tmp_path, score=90, eligible=True, automation_permitted=True, create_files=False, deadline=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{tmp_path / 'applications.db'}")
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = User(email="apply@example.com", password_hash="hash", first_name="Test", last_name="Candidate")
    source = JobSource(
        name="Permitted",
        base_url="https://jobs.example",
        connector_type="rss",
        config_json=json.dumps({"automation_permitted": automation_permitted}),
    )
    db.add_all([user, source])
    db.flush()
    db.add(CareerProfile(user_id=user.id, city="Nairobi", phone="+254700000000"))
    opportunity = Opportunity(
        source_id=source.id,
        external_id="apply-1",
        dedupe_hash="apply-1",
        title="Engineer",
        company="Example",
        url="https://jobs.example/apply",
        description="Python role",
        deadline=deadline,
    )
    db.add(opportunity)
    db.flush()
    db.add(JobMatch(user_id=user.id, opportunity_id=opportunity.id, score=score, eligible=eligible, analysis_json="{}"))
    if create_files:
        storage_root = tmp_path / "docs" / user.id
        storage_root.mkdir(parents=True, exist_ok=True)
    for kind in ("cv", "cover_letter"):
        filename = f"{kind}.pdf"
        if create_files:
            (tmp_path / "docs" / user.id / filename).write_bytes(b"%PDF-1.4\n")
        document = Document(
            user_id=user.id,
            name=filename,
            document_type=f"generated_{kind}",
            storage_key=filename,
            extracted_text=kind,
        )
        db.add(document)
        db.flush()
        db.add(
            GeneratedDocument(
                user_id=user.id,
                opportunity_id=opportunity.id,
                document_id=document.id,
                document_type=kind,
                file_format="pdf",
                template_name="entry_level",
                version=1,
                editable_text=kind,
            )
        )
    db.commit()
    return db, user, opportunity


def test_decision_thresholds_and_expired_status(tmp_path):
    assert classify_decision(92, True) == "automatic"
    assert classify_decision(84, True) == "approval_required"
    assert classify_decision(65, True) == "approval_required"
    assert classify_decision(64, True) == "rejected"
    assert classify_decision(95, False) == "rejected"

    db_low, user_low, opp_low = fixture(tmp_path / "low", score=60)
    low_app = prepare_application(db_low, user_low, opp_low, {"Email": "apply@example.com"})
    assert low_app.status == "rejected"

    db_exp, user_exp, opp_exp = fixture(tmp_path / "exp", score=92, deadline=datetime.now(timezone.utc) - timedelta(days=1))
    exp_app = prepare_application(db_exp, user_exp, opp_exp, {"Email": "apply@example.com"})
    assert exp_app.status == "expired"


def test_approval_queue_state_and_rejection(tmp_path):
    db, user, opportunity = fixture(tmp_path, score=70)
    application = prepare_application(db, user, opportunity, {"Email": "apply@example.com"})
    assert application.status == "pending_approval"
    assert db.scalar(select(ApprovalRequest.id).where(ApprovalRequest.application_id == application.id)) is not None
    assert db.scalar(select(Notification.id).where(Notification.user_id == user.id)) is not None
    counts = count_application_statuses(db, user.id)
    assert counts["submitted"] == 0
    assert counts["prepared_not_submitted"] == 1
    application.status = "rejected"
    db.commit()
    assert application.status == "rejected"


def test_mock_html_form_field_mapping_and_confirmation_verification(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "document_storage_dir", str(tmp_path / "docs"))
    db, user, opportunity = fixture(tmp_path, score=92, create_files=True)
    application = prepare_application(
        db,
        user,
        opportunity,
        {"Why Example": "I enjoy Python engineering.", "Experience Level": "Mid-level", "Consent": "yes"},
    )
    # Unconfirmed legal consent must block automatic submission until confirmed in ProfileFact
    assert application.status == "pending_approval"
    assert application.sensitive_declarations_verified is False

    # Re-test without sensitive question in answers, using mock HTML form with field mapping + confirmation
    db2, user2, opp2 = fixture(tmp_path / "html-ok", score=92, create_files=True)
    monkeypatch.setattr(settings, "document_storage_dir", str(tmp_path / "html-ok" / "docs"))
    app2 = prepare_application(
        db2,
        user2,
        opp2,
        {"Why Example": "I enjoy Python engineering.", "Experience Level": "Mid-level"},
    )
    assert app2.status == "ready_to_submit"

    form_html = """
    <html><body>
      <form id="apply-form">
        <label for="f_email">Email Address</label>
        <input id="f_email" name="candidate_email" type="email" required />
        <label for="f_level">Experience Level</label>
        <select id="f_level" name="exp_level" required>
          <option value="junior">Junior</option>
          <option value="mid">Mid-level</option>
        </select>
        <label for="f_why">Why Example</label>
        <textarea id="f_why" name="motivation" required></textarea>
        <label for="f_cv">Resume / CV</label>
        <input id="f_cv" name="resume_upload" type="file" required />
        <label for="f_cl">Cover Letter</label>
        <input id="f_cl" name="cover_upload" type="file" required />
        <input type="hidden" name="csrf_token" value="ignore-me" />
        <button type="submit">Submit Application</button>
      </form>
    </body></html>
    """

    def on_submit(page):
        page.html = "<html><body><h1>Thank you for applying!</h1><p>Confirmation ID: APP-2026-991</p></body></html>"

    factory, fake_page = make_fake_playwright_factory({"https://jobs.example/apply": form_html}, on_submit)
    adapter = PlaywrightBrowserAdapter(tmp_path / "audit", playwright_factory=factory)
    submitted = submit_application(db2, app2, adapter)
    adapter.close()

    assert submitted.status == "submitted"
    assert submitted.confirmation_reference == "APP-2026-991"
    assert submitted.submitted_at is not None
    assert fake_page.values["candidate_email"] == "apply@example.com"
    assert fake_page.values["exp_level"] == "Mid-level"
    assert fake_page.values["motivation"] == "I enjoy Python engineering."
    assert fake_page.files["resume_upload"].endswith("cv.pdf")
    assert fake_page.files["cover_upload"].endswith("cover_letter.pdf")
    assert "csrf_token" not in fake_page.values
    assert (tmp_path / "audit" / f"app-{app2.id}-attempt-1.png").is_file()
    assert db2.scalar(select(AuditLog.id).where(AuditLog.resource_id == app2.id, AuditLog.action == "application_submission_attempt")) is not None


def test_mock_html_form_validation_error_and_fee_captcha_pauses(tmp_path, monkeypatch):
    db, user, opportunity = fixture(tmp_path / "val", score=92, create_files=True)
    monkeypatch.setattr(settings, "document_storage_dir", str(tmp_path / "val" / "docs"))
    application = prepare_application(db, user, opportunity, {"Email": "apply@example.com"})

    form_html = """
    <html><body><form>
      <input name="email" type="email" aria-label="Email" required />
      <button type="submit">Submit</button>
    </form></body></html>
    """

    def on_validation_fail(page):
        page.html = "<html><body><div class='error' role='alert'>Validation error: Phone number is required</div></body></html>"

    factory, _ = make_fake_playwright_factory({"https://jobs.example/apply": form_html}, on_validation_fail)
    adapter = PlaywrightBrowserAdapter(tmp_path / "val_audit", playwright_factory=factory)
    failed = submit_application(db, application, adapter)
    adapter.close()
    assert failed.status == "failed"
    assert "Phone number is required" in (failed.last_error or "")
    assert failed.submitted_at is None
    assert count_application_statuses(db, user.id)["submitted"] == 0

    # Fee-gated form must pause and never pay application fees
    db_fee, user_fee, opp_fee = fixture(tmp_path / "fee", score=92, create_files=True)
    monkeypatch.setattr(settings, "document_storage_dir", str(tmp_path / "fee" / "docs"))
    app_fee = prepare_application(db_fee, user_fee, opp_fee, {"Email": "apply@example.com"})
    fee_html = "<html><body><form><p>Please pay $25 application fee to continue.</p><input name='card_number' /><button type='submit'>Pay</button></form></body></html>"
    fee_factory, _ = make_fake_playwright_factory({"https://jobs.example/apply": fee_html}, lambda _p: None)
    fee_adapter = PlaywrightBrowserAdapter(tmp_path / "fee_audit", playwright_factory=fee_factory)
    paused = submit_application(db_fee, app_fee, fee_adapter)
    fee_adapter.close()
    assert paused.status == "confirmation_pending"
    assert paused.requires_manual_intervention is True
    assert "fee" in (paused.last_error or "").lower()
    assert db_fee.scalar(select(Notification.id).where(Notification.user_id == user_fee.id)) is not None


def test_captcha_pauses_and_failed_submission_is_recorded(tmp_path):
    db, user, opportunity = fixture(tmp_path, score=90)
    application = prepare_application(db, user, opportunity, {"Email": "apply@example.com"})
    paused = submit_application(db, application, MockBrowser(manual=True))
    assert paused.status == "confirmation_pending"
    assert paused.requires_manual_intervention is True

    db2, user2, opportunity2 = fixture(tmp_path / "second", score=90)
    application2 = prepare_application(db2, user2, opportunity2, {"Email": "apply@example.com"})
    failed = submit_application(db2, application2, MockBrowser(SubmissionResult("failed", error="validation error")))
    assert failed.status == "failed"
    assert failed.last_error == "validation error"


def test_sensitive_declaration_cannot_cross_bypass(tmp_path):
    db, user, opportunity = fixture(tmp_path / "sens", score=92)
    db.add(ProfileFact(user_id=user.id, field_key="work_authorization", value="Yes", status="confirmed", source="user"))
    db.commit()
    app = prepare_application(db, user, opportunity, {"Legal declaration confirmed": "Yes"})
    assert app.sensitive_declarations_verified is False
    assert app.status == "pending_approval"


def test_duplicate_prevention_same_and_cross_source(tmp_path):
    db, user, opportunity = fixture(tmp_path)
    application = prepare_application(db, user, opportunity, {"Email": "apply@example.com"})
    submit_application(db, application, MockBrowser())
    same = prepare_application(db, user, opportunity, {"Email": "apply@example.com"})
    assert same.id == application.id
    assert same.status == "submitted"

    source2 = JobSource(name="Mirror", base_url="https://mirror.example", connector_type="rss", config_json=json.dumps({"automation_permitted": True}))
    db.add(source2)
    db.flush()
    opp2 = Opportunity(source_id=source2.id, external_id="mirror-1", dedupe_hash="mirror-hash", title="Engineer", company="Example", url="https://jobs.example/apply", description="Mirror")
    db.add(opp2)
    db.flush()
    db.add(JobMatch(user_id=user.id, opportunity_id=opp2.id, score=95, eligible=True, analysis_json="{}"))
    for kind in ("cv", "cover_letter"):
        doc = Document(user_id=user.id, name=f"{kind}2.pdf", document_type=f"generated_{kind}", storage_key=f"{kind}.pdf", extracted_text=kind)
        db.add(doc)
        db.flush()
        db.add(GeneratedDocument(user_id=user.id, opportunity_id=opp2.id, document_id=doc.id, document_type=kind, file_format="pdf", template_name="entry_level", version=1, editable_text=kind))
    db.commit()
    dup_app = prepare_application(db, user, opp2, {"Email": "apply@example.com"})
    assert dup_app.status == "pending_approval"


def test_approval_queue_preview_edit_approve_reject_and_counts_api(client, tmp_path):
    reg = client.post("/api/auth/register", json={"email": "owner@example.com", "password": "StrongPassword1", "first_name": "Ada", "last_name": "Lovelace"})
    assert reg.status_code == 201
    csrf = reg.cookies["jobhunter_csrf"]
    headers = {"X-CSRF-Token": csrf}

    assert client.put("/api/profile", headers=headers, json={"city": "Nairobi", "professional_summary": "Verified engineer"}).status_code == 200
    assert client.post("/api/profile/experience", headers=headers, json={"company": "Verified Co", "title": "Engineer"}).status_code == 201

    from app.db.session import get_db
    from app.main import app as fastapi_app

    db_gen = fastapi_app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        user = db.scalar(select(User).where(User.email == "owner@example.com"))
        source = JobSource(name="QueueSource", base_url="https://queue.example", connector_type="rss", config_json=json.dumps({"automation_permitted": True}))
        db.add(source)
        db.flush()
        opp = Opportunity(source_id=source.id, external_id="q-1", dedupe_hash="q-1", title="Backend Developer", company="Target Co", url="https://queue.example/apply", description="Build Python APIs")
        db.add(opp)
        db.flush()
        db.add(JobMatch(user_id=user.id, opportunity_id=opp.id, score=75, eligible=True, explanation="Good match", analysis_json="{}"))
        db.commit()
        generate_documents(db, user, opp, ["Why Target Co?"], ["pdf"])
        opp_id = opp.id
    finally:
        db_gen.close()

    prep = client.post(f"/api/applications/opportunities/{opp_id}/prepare", headers=headers, json={"answers": {"Why Target Co?": "Initial answer"}})
    assert prep.status_code == 200
    app_id = prep.json()["id"]
    assert prep.json()["status"] == "pending_approval"

    queue = client.get("/api/applications/queue")
    assert queue.status_code == 200
    assert len(queue.json()) == 1
    item = queue.json()[0]
    assert item["job"]["title"] == "Backend Developer"
    assert item["match_score"] == 75
    assert item["cv_preview"]
    assert item["cover_letter_preview"]
    assert item["answers"]["Why Target Co?"] == "Initial answer"

    # Reject unsupported claims in edited CV
    bad_edit = client.put(f"/api/applications/{app_id}", headers=headers, json={"cv_text": "I worked at Fabricated Corp in 2018."})
    assert bad_edit.status_code == 422

    # Valid edit before submission
    good_edit = client.put(
        f"/api/applications/{app_id}",
        headers=headers,
        json={"answers": {"Why Target Co?": "Updated verified answer"}, "cover_letter_text": "Ada Lovelace applying for Backend Developer at Target Co."},
    )
    assert good_edit.status_code == 200
    assert good_edit.json()["answers"]["Why Target Co?"] == "Updated verified answer"
    assert "Target Co" in good_edit.json()["cover_letter_preview"]

    # Prepared application is NOT counted as submitted
    listing = client.get("/api/applications")
    assert listing.status_code == 200
    assert listing.json()["counts"]["submitted"] == 0
    assert listing.json()["counts"]["prepared_not_submitted"] == 1

    # Approve and then test reject / withdraw
    assert client.post(f"/api/applications/{app_id}/approve", headers=headers).json()["status"] == "approved"
    assert client.post(f"/api/applications/{app_id}/reject", headers=headers, json={"reason": "Decided to wait"}).json()["status"] == "rejected"
    assert client.post(f"/api/applications/{app_id}/withdraw", headers=headers).json()["status"] == "withdrawn"
