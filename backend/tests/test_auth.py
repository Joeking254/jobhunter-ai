from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password, is_expired, verify_password


def registration_payload(email="person@example.com", password="StrongPassword1"):
    return {"email": email, "password": password, "first_name": "Test", "last_name": "Person"}


def test_registration_login_logout_and_session(client):
    response = client.post("/api/auth/register", json=registration_payload())
    assert response.status_code == 201
    assert response.json()["email"] == "person@example.com"
    assert "jobhunter_session" in response.cookies
    csrf = response.cookies["jobhunter_csrf"]

    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 403
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
    assert client.get("/api/auth/me").status_code == 401

    login = client.post("/api/auth/login", json={"email": "PERSON@example.com", "password": "StrongPassword1"})
    assert login.status_code == 200


def test_duplicate_registration_and_password_policy(client):
    assert client.post("/api/auth/register", json=registration_payload()).status_code == 201
    assert client.post("/api/auth/register", json=registration_payload()).status_code == 409
    weak = registration_payload(email="weak@example.com", password="short")
    assert client.post("/api/auth/register", json=weak).status_code == 422


def test_password_is_argon2id_and_reset_revokes_sessions(client):
    client.post("/api/auth/register", json=registration_payload())
    assert client.post("/api/auth/login", json={"email": "person@example.com", "password": "wrong-password"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "person@example.com", "password": "wrong-password"}).status_code == 401
    reset = client.post("/api/auth/password-reset/request", json={"email": "person@example.com"})
    token = reset.json()["development_token"]
    assert client.post("/api/auth/password-reset/confirm", json={"token": token, "new_password": "NewStrongPassword1"}).status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"email": "person@example.com", "password": "NewStrongPassword1"}).status_code == 200


def test_rate_limiting(client):
    for _ in range(5):
        assert client.post("/api/auth/login", json={"email": "missing@example.com", "password": "WrongPassword1"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "missing@example.com", "password": "WrongPassword1"}).status_code == 429


def test_password_security_and_schema_constraints(tmp_path):
    password_hash = hash_password("StrongPassword1")
    assert password_hash.startswith("$argon2id$")
    assert verify_password("StrongPassword1", password_hash)
    assert not verify_password("wrong", password_hash)
    engine = create_engine(f"sqlite:///{tmp_path / 'schema.db'}")
    from app.db.base import Base, import_models
    import_models()
    Base.metadata.create_all(engine)
    tables = set(inspect(engine).get_table_names())
    assert {"users", "career_profiles", "opportunities", "applications", "auth_sessions", "login_attempts"}.issubset(tables)


def test_session_expiration_is_rejected_by_expiry_rule():
    assert is_expired(datetime.now(timezone.utc) - timedelta(seconds=1))
    assert not is_expired(datetime.now(timezone.utc) + timedelta(minutes=1))


def test_job_and_application_duplicates_are_rejected(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'constraints.db'}")
    from app.db.base import Base, import_models
    from app.models.models import Application, JobSource, Opportunity, User
    import_models()
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="constraint@example.com", password_hash="hash", first_name="A", last_name="B")
        source = JobSource(name="Example", base_url="https://example.com")
        db.add_all([user, source])
        db.flush()
        opportunity = Opportunity(source_id=source.id, external_id="job-1", dedupe_hash="same-job", title="Engineer", company="Example", url="https://example.com/job-1")
        db.add(opportunity)
        db.commit()
        db.add(Opportunity(source_id=source.id, external_id="job-1", dedupe_hash="same-job-2", title="Engineer", company="Example", url="https://example.com/job-1"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.add_all([Application(user_id=user.id, opportunity_id=opportunity.id), Application(user_id=user.id, opportunity_id=opportunity.id)])
        with pytest.raises(IntegrityError):
            db.commit()
