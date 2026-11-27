from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db.base import Base, import_models
from app.models.models import AIProcessingHistory, CareerProfile, Education, JobSource, Opportunity, Skill, User, UserSettings
from app.services.ai.matching import match_opportunity

import_models()


def make_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'matching.db'}")
    Base.metadata.create_all(engine)
    return engine


def setup_user(db, *, work_authorization=None, remote_only=False):
    user = User(email="match@example.com", password_hash="hash", first_name="Test", last_name="Candidate")
    db.add(user)
    db.flush()
    db.add(UserSettings(user_id=user.id, work_authorization=work_authorization, remote_only=remote_only))
    db.add(CareerProfile(user_id=user.id, city="Nairobi", country="Kenya", professional_summary="Engineer"))
    db.add_all([Skill(user_id=user.id, name="Python", category="programming", years_experience=5), Skill(user_id=user.id, name="SQL", category="technical", years_experience=3)])
    db.add(Education(user_id=user.id, institution="University", qualification="BSc", field_of_study="Computer Science"))
    db.flush()
    return user


def opportunity(db, source, **kwargs):
    values = {"source_id": source.id, "external_id": kwargs.pop("external_id", "job-1"), "dedupe_hash": kwargs.pop("dedupe_hash", kwargs.get("title", "job").lower()), "title": "Python Engineer", "company": "Example", "url": "https://example/job", "description": "Python SQL role with 3 years experience", "location": "Nairobi", "remote_only": False}
    values.update(kwargs)
    item = Opportunity(**values)
    db.add(item)
    db.flush()
    return item


def test_strong_match_and_analysis_cache(tmp_path):
    engine = make_db(tmp_path)
    with Session(engine) as db:
        source = JobSource(name="Matching", base_url="https://matching", connector_type="rss")
        db.add(source)
        db.flush()
        user = setup_user(db)
        job = opportunity(db, source)
        result = match_opportunity(db, user, job)
        assert result["match_score"] >= 85
        assert result["eligibility_assessment"]["eligible"] is True
        before = db.scalar(select(func.count(AIProcessingHistory.id)))
        match_opportunity(db, user, job)
        assert db.scalar(select(func.count(AIProcessingHistory.id))) == before


def test_partial_match_requires_approval_or_is_not_recommended(tmp_path):
    engine = make_db(tmp_path)
    with Session(engine) as db:
        source = JobSource(name="Partial", base_url="https://partial", connector_type="rss")
        db.add(source)
        db.flush()
        user = setup_user(db)
        job = opportunity(db, source, title="Machine Learning Researcher", description="Machine learning Kubernetes deep learning role requiring 8 years experience", external_id="partial", dedupe_hash="partial")
        result = match_opportunity(db, user, job)
        assert result["match_score"] < 85
        assert result["recommended_next_action"] in {"Request approval", "Do not apply"}


def test_authorization_and_expiration_override_score(tmp_path):
    engine = make_db(tmp_path)
    with Session(engine) as db:
        source = JobSource(name="Restricted", base_url="https://restricted", connector_type="rss")
        db.add(source)
        db.flush()
        user = setup_user(db)
        restricted = opportunity(db, source, external_id="restricted", dedupe_hash="restricted", description="Python role. Applicants must be authorized to work in the United States.")
        result = match_opportunity(db, user, restricted)
        assert result["eligibility_assessment"]["eligible"] is False
        assert result["match_score"] == 0
        expired = opportunity(db, source, external_id="expired", dedupe_hash="expired", deadline=datetime.now(timezone.utc) - timedelta(days=1))
        expired_result = match_opportunity(db, user, expired)
        assert expired_result["eligibility_assessment"]["eligible"] is False
        assert expired_result["match_score"] == 0


def test_remote_preference_is_supported(tmp_path):
    engine = make_db(tmp_path)
    with Session(engine) as db:
        source = JobSource(name="Remote", base_url="https://remote", connector_type="rss")
        db.add(source)
        db.flush()
        user = setup_user(db, remote_only=True)
        job = opportunity(db, source, external_id="remote", dedupe_hash="remote", location="Worldwide", remote_only=True)
        result = match_opportunity(db, user, job)
        assert result["eligibility_assessment"]["eligible"] is True


def test_gemini_provider_parses_structured_analysis(monkeypatch):
    from app.core.config import settings
    from app.services.ai.providers import GeminiProvider, get_provider, resolved_ai_model

    captured: dict = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": '{"job_category":"Software development","required_skills":["python","sql"],"education_requirements":[],"eligibility_restrictions":[],"experience_requirements":"2+ years","risk_warnings":[],"risk_level":"low","salary":{}}'
                                }
                            ]
                        }
                    }
                ]
            }

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr("app.services.ai.providers.httpx.post", fake_post)
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    monkeypatch.setattr(settings, "ai_api_key", "test-gemini-key")
    monkeypatch.setattr(settings, "ai_model", "configured-model")
    monkeypatch.setattr(settings, "ai_api_url", None)

    provider = get_provider()
    assert isinstance(provider, GeminiProvider)
    assert resolved_ai_model() == "gemini-3.8-flash"
    result = provider.analyze_job({"title": "Python Dev"})
    assert result["required_skills"] == ["python", "sql"]
    assert captured["url"].endswith("/models/gemini-3.8-flash:generateContent")
    assert captured["headers"]["x-goog-api-key"] == "test-gemini-key"


def test_gemini_aq_key_falls_back_to_vertex_express(monkeypatch):
    from app.services.ai.providers import post_gemini_json

    called_urls: list[str] = []

    class Resp:
        def __init__(self, status_code: int, body: dict):
            self.status_code = status_code
            self._body = body

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self) -> dict:
            return self._body

    def fake_post(url, headers=None, json=None, timeout=None):
        called_urls.append(url)
        if "generativelanguage" in url:
            return Resp(401, {"error": "unauthorized"})
        return Resp(200, {"candidates": [{"content": {"parts": [{"text": '{"job_category":"IT"}'}]}}]})

    monkeypatch.setattr("app.services.ai.providers.httpx.post", fake_post)
    out = post_gemini_json("analyze", "AQ.fake-express-key", "gemini-2.5-flash")
    assert out == {"job_category": "IT"}
    assert len(called_urls) == 2
    assert "aiplatform.googleapis.com" in called_urls[1]
