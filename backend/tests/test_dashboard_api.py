from datetime import datetime, timedelta, timezone
import json

from sqlalchemy import select

from app.db.session import get_db
from app.main import app as fastapi_app
from app.models.models import Application, JobMatch, JobSource, Opportunity, User


def _register(client, email="dash@example.com"):
    res = client.post(
        "/api/auth/register",
        json={"email": email, "password": "StrongPassword1", "first_name": "Ada", "last_name": "Lovelace"},
    )
    assert res.status_code == 201
    return res.cookies["jobhunter_csrf"], {"X-CSRF-Token": res.cookies["jobhunter_csrf"]}


def test_dashboard_overview_opportunities_analytics_and_settings(client):
    _csrf, headers = _register(client)

    db_gen = fastapi_app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        user = db.scalar(select(User).where(User.email == "dash@example.com"))
        source = JobSource(
            name="RemoteBoard",
            base_url="https://remote.example",
            connector_type="rss",
            config_json=json.dumps({"automation_permitted": True}),
        )
        db.add(source)
        db.flush()
        opp1 = Opportunity(
            source_id=source.id,
            external_id="o-1",
            dedupe_hash="o-1",
            title="Senior Python Engineer",
            company="Alpha Labs",
            location="Remote",
            url="https://remote.example/1",
            description="Python FastAPI",
            salary_text="$120k-$150k",
            salary_max=150000,
            remote_only=True,
            categories="software_development",
            deadline=datetime.now(timezone.utc) + timedelta(days=5),
            posted_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        opp2 = Opportunity(
            source_id=source.id,
            external_id="o-2",
            dedupe_hash="o-2",
            title="Data Analyst",
            company="Beta Corp",
            location="Nairobi",
            url="https://remote.example/2",
            description="SQL BI",
            salary_text="$60k",
            salary_max=60000,
            remote_only=False,
            categories="data_annotation",
            posted_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
        db.add_all([opp1, opp2])
        db.flush()
        db.add_all([
            JobMatch(user_id=user.id, opportunity_id=opp1.id, score=92, eligible=True, explanation="Strong fit", analysis_json=json.dumps({"job_category": "software_development", "missing_skills": []})),
            JobMatch(user_id=user.id, opportunity_id=opp2.id, score=72, eligible=True, explanation="Partial fit", analysis_json=json.dumps({"job_category": "data_annotation", "missing_skills": ["tableau"]})),
        ])
        app1 = Application(
            user_id=user.id,
            opportunity_id=opp1.id,
            status="submitted",
            application_url=opp1.url,
            confirmation_reference="REF-900",
            submitted_at=datetime.now(timezone.utc),
        )
        app2 = Application(
            user_id=user.id,
            opportunity_id=opp2.id,
            status="pending_approval",
            application_url=opp2.url,
        )
        db.add_all([app1, app2])
        db.commit()
        app1_id = app1.id
    finally:
        db_gen.close()

    # Overview reflects real database totals
    ov = client.get("/api/dashboard/overview")
    assert ov.status_code == 200
    data = ov.json()
    assert data["total_opportunities"] == 2
    assert data["strong_matches"] == 1
    assert data["pending_approvals"] == 1
    assert data["applications_submitted"] == 1

    # Opportunities search, filter, sort, pagination
    all_opps = client.get("/api/opportunities?page=1&page_size=1&sort_by=score&sort_dir=desc")
    assert all_opps.status_code == 200
    assert all_opps.json()["total"] == 2
    assert all_opps.json()["total_pages"] == 2
    assert all_opps.json()["items"][0]["title"] == "Senior Python Engineer"

    filtered = client.get("/api/opportunities?q=Beta&recommended_only=true")
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["missing_skills"] == ["tableau"]

    # Interviews CRUD
    iv_create = client.post(
        "/api/interviews",
        headers=headers,
        json={"application_id": app1_id, "scheduled_at": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(), "interview_type": "System Design", "notes": "Panel"},
    )
    assert iv_create.status_code == 201
    iv_id = iv_create.json()["id"]
    assert len(client.get("/api/interviews").json()) == 1

    # Analytics reflects real DB data including interview conversion
    an = client.get("/api/dashboard/analytics")
    assert an.status_code == 200
    analytics = an.json()
    assert analytics["interview_conversion"]["submitted"] == 1
    assert analytics["interview_conversion"]["interviews"] == 1
    assert analytics["interview_conversion"]["conversion_rate_pct"] == 100.0
    assert len(analytics["source_performance"]) == 1
    assert sum(b["count"] for b in analytics["match_distribution"]) == 2

    # Saved searches CRUD
    ss = client.post("/api/saved-searches", headers=headers, json={"name": "Remote Python", "query": "python", "filters": {"remote_only": True}})
    assert ss.status_code == 201
    ss_id = ss.json()["id"]
    assert len(client.get("/api/saved-searches").json()) == 1
    assert client.put(f"/api/saved-searches/{ss_id}", headers=headers, json={"is_active": False}).json()["is_active"] is False
    assert client.delete(f"/api/saved-searches/{ss_id}", headers=headers).status_code == 204

    # AI config & Account update
    ai_cfg = client.put("/api/dashboard/ai-config", headers=headers, json={"remote_only": True, "preferred_locations": "Remote, Nairobi"})
    assert ai_cfg.status_code == 200
    assert ai_cfg.json()["preferences"]["remote_only"] is True

    acct = client.put("/api/auth/account", headers=headers, json={"first_name": "Augusta", "timezone": "Africa/Nairobi"})
    assert acct.status_code == 200
    assert acct.json()["first_name"] == "Augusta"
    assert acct.json()["timezone"] == "Africa/Nairobi"

    # Delete interview
    assert client.delete(f"/api/interviews/{iv_id}", headers=headers).status_code == 204
