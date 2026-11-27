"""Initial JOBHUNTER AI account and job schema."""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _ts():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        *_ts(),
        sa.Column("email", sa.String(320), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("first_name", sa.String(120), nullable=False),
        sa.Column("last_name", sa.String(120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_users_email_active", "users", ["email", "is_active"])

    op.create_table(
        "career_profiles",
        *_ts(),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False),
        sa.Column("headline", sa.String(255)),
        sa.Column("summary", sa.Text()),
        sa.Column("location", sa.String(255)),
        sa.Column("target_titles", sa.Text()),
    )

    op.create_table(
        "education",
        *_ts(),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("institution", sa.String(255), nullable=False),
        sa.Column("degree", sa.String(255)),
        sa.Column("field_of_study", sa.String(255)),
        sa.Column("start_date", sa.DateTime()),
        sa.Column("end_date", sa.DateTime()),
    )
    op.create_index("ix_education_user", "education", ["user_id"])

    op.create_table(
        "experience",
        *_ts(),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company", sa.String(255), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("start_date", sa.DateTime()),
        sa.Column("end_date", sa.DateTime()),
    )
    op.create_index("ix_experience_user", "experience", ["user_id"])

    op.create_table(
        "skills",
        *_ts(),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("proficiency", sa.String(50)),
        sa.UniqueConstraint("user_id", "name", name="uq_skill_user_name"),
    )
    op.create_index("ix_skills_name", "skills", ["name"])

    op.create_table(
        "documents",
        *_ts(),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("document_type", sa.String(50), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("content_hash", sa.String(128)),
    )
    op.create_index("ix_documents_user_type", "documents", ["user_id", "document_type"])

    op.create_table(
        "job_sources",
        *_ts(),
        sa.Column("name", sa.String(120), unique=True, nullable=False),
        sa.Column("base_url", sa.String(512), unique=True, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
    )

    op.create_table(
        "opportunities",
        *_ts(),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("job_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("dedupe_hash", sa.String(128), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("company", sa.String(255), nullable=False),
        sa.Column("location", sa.String(255)),
        sa.Column("url", sa.String(1024), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("source_id", "external_id", name="uq_opportunity_source_external"),
        sa.UniqueConstraint("dedupe_hash", name="uq_opportunity_dedupe_hash"),
    )
    op.create_index("ix_opportunities_company_title", "opportunities", ["company", "title"])
    op.create_index("ix_opportunities_posted_at", "opportunities", ["posted_at"])

    op.create_table(
        "job_matches",
        *_ts(),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("opportunity_id", sa.String(36), sa.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("explanation", sa.Text()),
        sa.UniqueConstraint("user_id", "opportunity_id", name="uq_job_match_user_opportunity"),
    )
    op.create_index("ix_job_matches_user_score", "job_matches", ["user_id", "score"])

    op.create_table(
        "applications",
        *_ts(),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("opportunity_id", sa.String(36), sa.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="discovered"),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "opportunity_id", name="uq_application_user_opportunity"),
    )
    op.create_index("ix_applications_user_status", "applications", ["user_id", "status"])

    op.create_table(
        "application_answers",
        *_ts(),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_key", sa.String(255), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.UniqueConstraint("application_id", "question_key", name="uq_application_answer"),
    )

    op.create_table(
        "application_documents",
        *_ts(),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("application_id", "document_id", name="uq_application_document"),
    )

    op.create_table(
        "interviews",
        *_ts(),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interview_type", sa.String(80)),
        sa.Column("notes", sa.Text()),
    )
    op.create_index("ix_interviews_scheduled", "interviews", ["scheduled_at"])

    op.create_table(
        "notifications",
        *_ts(),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_notifications_user_read", "notifications", ["user_id", "read_at"])

    op.create_table(
        "bot_runs",
        *_ts(),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("bot_name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text()),
    )

    op.create_table(
        "audit_logs",
        *_ts(),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("resource_type", sa.String(120)),
        sa.Column("resource_id", sa.String(36)),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("details", sa.Text()),
    )
    op.create_index("ix_audit_logs_user_created", "audit_logs", ["user_id", "created_at"])

    op.create_table(
        "user_settings",
        *_ts(),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("locale", sa.String(16), nullable=False, server_default="en"),
    )

    op.create_table(
        "saved_searches",
        *_ts(),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("query", sa.Text()),
        sa.Column("filters", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.UniqueConstraint("user_id", "name", name="uq_saved_search_user_name"),
    )
    op.create_index("ix_saved_searches_user_active", "saved_searches", ["user_id", "is_active"])

    op.create_table(
        "approval_requests",
        *_ts(),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id", ondelete="CASCADE")),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("reviewed_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "application_attempts",
        *_ts(),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("response_code", sa.Integer()),
        sa.Column("error_message", sa.Text()),
        sa.UniqueConstraint("application_id", "attempt_number", name="uq_application_attempt_number"),
    )

    op.create_table(
        "source_credentials",
        *_ts(),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("job_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "source_id", name="uq_source_credential_user_source"),
    )

    op.create_table(
        "notification_preferences",
        *_ts(),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.UniqueConstraint("user_id", "channel", "event_type", name="uq_notification_preference"),
    )

    op.create_table(
        "ai_processing_history",
        *_ts(),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("entity_type", sa.String(80), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("processor", sa.String(120), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("input_hash", sa.String(128)),
        sa.Column("output", sa.Text()),
    )
    op.create_index("ix_ai_history_entity", "ai_processing_history", ["entity_type", "entity_id"])

    op.create_table(
        "auth_sessions",
        *_ts(),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(128), unique=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("user_agent", sa.String(512)),
    )
    op.create_index("ix_auth_sessions_user_expires", "auth_sessions", ["user_id", "expires_at"])

    op.create_table(
        "password_reset_tokens",
        *_ts(),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(128), unique=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_password_reset_user_expires", "password_reset_tokens", ["user_id", "expires_at"])

    op.create_table(
        "login_attempts",
        *_ts(),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_login_attempts_email_created", "login_attempts", ["email", "created_at"])
    op.create_index("ix_login_attempts_ip_created", "login_attempts", ["ip_address", "created_at"])


def downgrade() -> None:
    for table in [
        "login_attempts",
        "password_reset_tokens",
        "auth_sessions",
        "ai_processing_history",
        "notification_preferences",
        "source_credentials",
        "application_attempts",
        "approval_requests",
        "saved_searches",
        "user_settings",
        "audit_logs",
        "bot_runs",
        "notifications",
        "interviews",
        "application_documents",
        "application_answers",
        "applications",
        "job_matches",
        "opportunities",
        "job_sources",
        "documents",
        "skills",
        "experience",
        "education",
        "career_profiles",
        "users",
    ]:
        op.drop_table(table)
