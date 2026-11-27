from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base, import_models
from app.models.models import CareerProfile, Education, Experience, JobSource, Opportunity, Skill, User
from app.services.generation.service import generate_documents, unsupported_claims, verified_context

import_models()


def test_generated_documents_use_verified_profile_and_versions(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.generation.service.settings.document_storage_dir", str(tmp_path / "private"))
    engine = create_engine(f"sqlite:///{tmp_path / 'generation.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="writer@example.com", password_hash="hash", first_name="Ada", last_name="Lovelace")
        source = JobSource(name="Gen", base_url="https://gen", connector_type="rss")
        db.add_all([user, source])
        db.flush()
        db.add(CareerProfile(user_id=user.id, phone="+254700000000", city="Nairobi", professional_summary="Verified software engineer"))
        db.add_all([Skill(user_id=user.id, name="Python", category="programming"), Education(user_id=user.id, institution="University", qualification="BSc", field_of_study="Computer Science"), Experience(user_id=user.id, company="Verified Co", title="Engineer")])
        job = Opportunity(source_id=source.id, external_id="gen-1", dedupe_hash="gen-1", title="Software development intern", company="Target Co", url="https://target/job", description="Build software with Python")
        db.add(job)
        db.flush()
        rows = generate_documents(db, user, job, ["Why are you interested?", "What skills do you have?"], ["docx", "pdf"])
        assert len(rows) == 6
        assert {row.document_type for row in rows} == {"cv", "cover_letter", "application_answers"}
        assert all((Path(tmp_path / "private" / user.id) / f"generated-{row.document_id}.{row.file_format}").is_file() for row in rows)
        assert all("Verified Co" in row.editable_text or row.document_type == "application_answers" for row in rows if row.document_type != "cover_letter")
        assert all("invented" not in row.editable_text.lower() for row in rows)
        context = verified_context(db, user, job, [])
        assert unsupported_claims("I worked at Fabricated Corp in 2020.", context) == ["Fabricated Corp", "2020"]
        regenerated = generate_documents(db, user, job, [], ["pdf"])
        assert all(row.version == 2 for row in regenerated)


def test_gemini_generation_provider(monkeypatch):
    from app.core.config import settings
    from app.services.generation.providers import GeminiGenerationProvider, get_generation_provider

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": '{"cv":"Ada Lovelace CV","cover_letter":"Dear Hiring Team","answers":{"Why?":"Verified Python"}}'
                                }
                            ]
                        }
                    }
                ]
            }

    monkeypatch.setattr("app.services.ai.providers.httpx.post", lambda *a, **kw: FakeResponse())
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    monkeypatch.setattr(settings, "ai_api_key", "test-gemini-key")
    monkeypatch.setattr(settings, "ai_model", "gemini-2.5-flash")

    provider = get_generation_provider()
    assert isinstance(provider, GeminiGenerationProvider)
    out = provider.generate({"job": {"title": "Dev"}, "profile": {}, "questions": ["Why?"]})
    assert out["cv"] == "Ada Lovelace CV"
    assert out["answers"] == {"Why?": "Verified Python"}
