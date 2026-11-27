from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import sqlite3

from alembic import command
from alembic.config import Config
import pytest
from reportlab.pdfgen import canvas
from sqlalchemy import create_engine, inspect, select

from app.core.config import Settings
from app.core.security import decrypt_secret, encrypt_secret
from app.db.session import get_db
from app.main import app as fastapi_app
from app.models.models import Application, BotRun, JobSource, SourceExecutionHistory, User
from scripts.backup import backup_database, prune_old_backups, restore_database, verify_backup_checksum


def _make_pdf_bytes() -> bytes:
    stream = BytesIO()
    pdf = canvas.Canvas(stream)
    pdf.drawString(72, 720, "Ada Lovelace Production CV")
    pdf.save()
    return stream.getvalue()


def test_production_settings_hardening():
    with pytest.raises(ValueError, match="COOKIE_SECURE"):
        Settings(app_env="production", secret_key="A" * 40, mysql_password="StrongDbPassword1", cookie_secure=False)

    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(app_env="production", secret_key="short", mysql_password="StrongDbPassword1", cookie_secure=True)

    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(app_env="production", secret_key="replace-with-a-long-random-secret-here", mysql_password="StrongDbPassword1", cookie_secure=True)

    with pytest.raises(ValueError, match="MYSQL_PASSWORD"):
        Settings(app_env="production", secret_key="X" * 48, mysql_password="replace-with-password", cookie_secure=True)

    ok = Settings(app_env="production", secret_key="X" * 48, mysql_password="UniqueStrongPassword1", cookie_secure=True)
    assert ok.cookie_secure is True


def test_credential_encryption_and_tamper_detection():
    secret = "oauth-refresh-token-123456"
    encrypted = encrypt_secret(secret)
    assert encrypted != secret
    assert encrypted.startswith("v1:")
    assert decrypt_secret(encrypted) == secret

    tampered = encrypted[:-4] + ("AAAA" if encrypted[-4:] != "AAAA" else "BBBB")
    with pytest.raises(ValueError):
        decrypt_secret(tampered)


def test_alembic_migrations_upgrade_head(tmp_path, monkeypatch):
    db_path = tmp_path / "migrations.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {"users", "applications", "bot_configs", "bot_runs", "notification_delivery_logs", "source_credentials"}.issubset(tables)


def test_backup_checksum_retention_and_restore(tmp_path):
    src_db = tmp_path / "source.db"
    conn = sqlite3.connect(str(src_db))
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO items (name) VALUES ('verified-row')")
    conn.commit()
    conn.close()

    backup_dir = tmp_path / "backups"
    gz_path = backup_database(backup_dir, retention_days=14, sqlite_path=src_db)
    assert gz_path.is_file()
    assert verify_backup_checksum(gz_path) is True

    # Old backup is pruned by retention policy
    stale = backup_dir / "jobhunter_20200101T000000Z.sql.gz"
    stale.write_bytes(b"old")
    stale.with_suffix(".gz.sha256").write_text("deadbeef  old\n", encoding="utf-8")
    old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
    os.utime(stale, (old_ts, old_ts))
    assert prune_old_backups(backup_dir, 14) == 1
    assert not stale.exists()

    # Restore into fresh target DB and verify data
    restored_db = tmp_path / "restored.db"
    restore_database(gz_path, sqlite_target=restored_db)
    rconn = sqlite3.connect(str(restored_db))
    row = rconn.execute("SELECT name FROM items").fetchone()
    rconn.close()
    assert row == ("verified-row",)


def test_security_headers_monitoring_and_full_integration(client):
    reg = client.post(
        "/api/auth/register",
        json={"email": "prod@example.com", "password": "StrongPassword1", "first_name": "Ada", "last_name": "Lovelace"},
    )
    assert reg.status_code == 201
    assert reg.headers.get("X-Content-Type-Options") == "nosniff"
    assert reg.headers.get("X-Frame-Options") == "DENY"
    assert reg.headers.get("Cache-Control") == "no-store"

    csrf = reg.cookies["jobhunter_csrf"]
    headers = {"X-CSRF-Token": csrf}

    # Upload CV & build profile
    up = client.post(
        "/api/documents",
        headers=headers,
        data={"category": "cv", "is_default": "true"},
        files={"file": ("cv.pdf", _make_pdf_bytes(), "application/pdf")},
    )
    assert up.status_code == 201
    assert client.put("/api/profile", headers=headers, json={"city": "Nairobi", "country": "Kenya", "professional_summary": "Backend Engineer"}).status_code == 200
    assert client.post("/api/profile/skills", headers=headers, json={"name": "Python", "category": "programming", "years_experience": 4}).status_code == 201

    # Seed source failure, task failure, and application failure to verify monitoring counters
    db_gen = fastapi_app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        user = db.scalar(select(User).where(User.email == "prod@example.com"))
        src = JobSource(name="ProdBoard", base_url="https://prod.example", connector_type="rss", config_json=json.dumps({"automation_permitted": True}))
        db.add(src)
        db.flush()
        db.add(SourceExecutionHistory(source_id=src.id, status="failed", started_at=datetime.now(timezone.utc), error_message="Timeout"))
        db.add(BotRun(user_id=user.id, bot_name="discover_opportunities", queue_name="discovery", status="failed", started_at=datetime.now(timezone.utc), error_message="Network"))
        from app.models.models import Opportunity
        opp = Opportunity(source_id=src.id, external_id="p-1", dedupe_hash="p-1", title="Python Engineer", company="ProdCo", url="https://prod.example/1", description="Python API")
        db.add(opp)
        db.flush()
        db.add(Application(user_id=user.id, opportunity_id=opp.id, status="failed", application_url=opp.url, last_error="Validation error"))
        db.commit()
    finally:
        db_gen.close()

    mon = client.get("/api/monitoring/summary")
    assert mon.status_code == 200
    body = mon.json()
    assert body["system"]["cpu"]["cpu_count"] >= 1
    assert body["system"]["disk"]["total_gb"] > 0
    assert body["services"]["database"]["status"] == "ok"
    assert body["failures_24h"]["failed_tasks"] >= 1
    assert body["failures_24h"]["source_failures"] >= 1
    assert body["failures_24h"]["application_failures"] >= 1

    # Live health & overview integration
    assert client.get("/api/health/live").status_code == 200
    assert client.get("/api/dashboard/overview").status_code == 200
    assert client.get("/api/dashboard/analytics").status_code == 200
