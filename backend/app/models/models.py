"""Database models for the JOBHUNTER AI account and job domain."""

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def new_id() -> str:
    return str(uuid4())


class TimestampMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_email_active", "email", "is_active"),)

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    first_name: Mapped[str] = mapped_column(String(120), nullable=False)
    last_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    settings = relationship("UserSettings", back_populates="user", uselist=False, cascade="all, delete-orphan")


class CareerProfile(TimestampMixin, Base):
    __tablename__ = "career_profiles"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    headline: Mapped[str | None] = mapped_column(String(255))
    summary: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(255))
    target_titles: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(40))
    country: Mapped[str | None] = mapped_column(String(120))
    city: Mapped[str | None] = mapped_column(String(120))
    professional_summary: Mapped[str | None] = mapped_column(Text)
    portfolio_links: Mapped[str | None] = mapped_column(Text)
    linkedin_url: Mapped[str | None] = mapped_column(String(512))


class Education(TimestampMixin, Base):
    __tablename__ = "education"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    institution: Mapped[str] = mapped_column(String(255), nullable=False)
    degree: Mapped[str | None] = mapped_column(String(255))
    qualification: Mapped[str | None] = mapped_column(String(255))
    field_of_study: Mapped[str | None] = mapped_column(String(255))
    start_date: Mapped[datetime | None] = mapped_column(DateTime)
    end_date: Mapped[datetime | None] = mapped_column(DateTime)
    current_status: Mapped[str | None] = mapped_column(String(50))
    __table_args__ = (Index("ix_education_user", "user_id"),)


class Experience(TimestampMixin, Base):
    __tablename__ = "experience"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    employment_type: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)
    achievements: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[datetime | None] = mapped_column(DateTime)
    end_date: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (Index("ix_experience_user", "user_id"),)


class Skill(TimestampMixin, Base):
    __tablename__ = "skills"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(80), default="technical", nullable=False)
    proficiency: Mapped[str | None] = mapped_column(String(50))
    years_experience: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_skill_user_name"), Index("ix_skills_name", "name"))


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(128))
    mime_type: Mapped[str | None] = mapped_column(String(120))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    replaced_document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    __table_args__ = (Index("ix_documents_user_type", "user_id", "document_type"),)


class JobSource(TimestampMixin, Base):
    __tablename__ = "job_sources"
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    connector_type: Mapped[str] = mapped_column(String(80), default="rss", nullable=False)
    config_json: Mapped[str | None] = mapped_column(Text)
    reliability_score: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Opportunity(TimestampMixin, Base):
    __tablename__ = "opportunities"
    source_id: Mapped[str] = mapped_column(ForeignKey("job_sources.id", ondelete="CASCADE"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    dedupe_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    experience_requirements: Mapped[str | None] = mapped_column(Text)
    salary_text: Mapped[str | None] = mapped_column(String(255))
    salary_min: Mapped[int | None] = mapped_column(Integer)
    salary_max: Mapped[int | None] = mapped_column(Integer)
    salary_currency: Mapped[str | None] = mapped_column(String(10))
    remote_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    categories: Mapped[str | None] = mapped_column(Text)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("source_id", "external_id", name="uq_opportunity_source_external"), UniqueConstraint("dedupe_hash", name="uq_opportunity_dedupe_hash"), Index("ix_opportunities_company_title", "company", "title"), Index("ix_opportunities_posted_at", "posted_at"), Index("ix_opportunities_remote_deadline", "remote_only", "deadline"), Index("ix_opportunities_source_expired", "source_id", "expired_at"))


class SourceExecutionHistory(TimestampMixin, Base):
    __tablename__ = "source_execution_history"
    source_id: Mapped[str] = mapped_column(ForeignKey("job_sources.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fetched_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (Index("ix_source_history_source_started", "source_id", "started_at"),)


class JobMatch(TimestampMixin, Base):
    __tablename__ = "job_matches"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text)
    eligible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    risk_level: Mapped[str | None] = mapped_column(String(30))
    analysis_json: Mapped[str | None] = mapped_column(Text)
    recommended_cv_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    next_action: Mapped[str | None] = mapped_column(String(120))
    __table_args__ = (UniqueConstraint("user_id", "opportunity_id", name="uq_job_match_user_opportunity"), Index("ix_job_matches_user_score", "user_id", "score"), Index("ix_job_matches_user_eligible", "user_id", "eligible"))


class ApplicationStatus(StrEnum):
    DISCOVERED = "discovered"
    ANALYZING = "analyzing"
    MATCHED = "matched"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    PREPARING = "preparing"
    READY_TO_SUBMIT = "ready_to_submit"
    SUBMITTING = "submitting"
    SUBMITTED = "submitted"
    CONFIRMATION_PENDING = "confirmation_pending"
    FAILED = "failed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    OFFER = "offer"
    WITHDRAWN = "withdrawn"


class Application(TimestampMixin, Base):
    __tablename__ = "applications"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default=ApplicationStatus.DISCOVERED.value, nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    application_url: Mapped[str | None] = mapped_column(String(1024))
    confirmation_reference: Mapped[str | None] = mapped_column(String(255))
    last_error: Mapped[str | None] = mapped_column(Text)
    prepared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requires_manual_intervention: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_permits_automation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    required_documents_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    required_answers_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sensitive_declarations_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    __table_args__ = (UniqueConstraint("user_id", "opportunity_id", name="uq_application_user_opportunity"), Index("ix_applications_user_status", "user_id", "status"), Index("ix_applications_user_submitted", "user_id", "submitted_at"))


class ApplicationAnswer(TimestampMixin, Base):
    __tablename__ = "application_answers"
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    question_key: Mapped[str] = mapped_column(String(255), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (UniqueConstraint("application_id", "question_key", name="uq_application_answer"),)


class ApplicationDocument(TimestampMixin, Base):
    __tablename__ = "application_documents"
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    __table_args__ = (UniqueConstraint("application_id", "document_id", name="uq_application_document"),)


class GeneratedDocument(TimestampMixin, Base):
    __tablename__ = "generated_documents"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    document_type: Mapped[str] = mapped_column(String(40), nullable=False)
    file_format: Mapped[str] = mapped_column(String(10), nullable=False)
    template_name: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    editable_text: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_hash: Mapped[str | None] = mapped_column(String(128))
    claims_json: Mapped[str | None] = mapped_column(Text)
    generation_status: Mapped[str] = mapped_column(String(30), default="ready", nullable=False)
    __table_args__ = (Index("ix_generated_documents_user_opportunity", "user_id", "opportunity_id"), UniqueConstraint("document_id", name="uq_generated_document_document"))


class Interview(TimestampMixin, Base):
    __tablename__ = "interviews"
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    interview_type: Mapped[str | None] = mapped_column(String(80))
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (Index("ix_interviews_scheduled", "scheduled_at"),)


class Notification(TimestampMixin, Base):
    __tablename__ = "notifications"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_notifications_user_read", "user_id", "read_at"),)


class BotRun(TimestampMixin, Base):
    __tablename__ = "bot_runs"
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    bot_name: Mapped[str] = mapped_column(String(120), nullable=False)
    queue_name: Mapped[str] = mapped_column(String(60), default="default", nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    details_json: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (Index("ix_bot_runs_name_started", "bot_name", "started_at"),)


class BotConfig(TimestampMixin, Base):
    __tablename__ = "bot_configs"
    scope_key: Mapped[str] = mapped_column(String(40), default="global", unique=True, nullable=False)
    bot_paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_apply_paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    search_frequency_minutes: Mapped[int] = mapped_column(Integer, default=360, nullable=False)
    match_strong_threshold: Mapped[int] = mapped_column(Integer, default=85, nullable=False)
    match_approval_threshold: Mapped[int] = mapped_column(Integer, default=65, nullable=False)
    last_discovery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_analytics_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_logs"
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(120))
    resource_id: Mapped[str | None] = mapped_column(String(36))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (Index("ix_audit_logs_user_created", "user_id", "created_at"),)


class UserSettings(TimestampMixin, Base):
    __tablename__ = "user_settings"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    locale: Mapped[str] = mapped_column(String(16), default="en", nullable=False)
    work_authorization: Mapped[str | None] = mapped_column(String(120))
    preferred_locations: Mapped[str | None] = mapped_column(Text)
    remote_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    opportunity_types: Mapped[str | None] = mapped_column(Text)
    career_preferences: Mapped[str | None] = mapped_column(Text)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(120))
    telegram_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notification_frequency: Mapped[str] = mapped_column(String(20), default="immediate", nullable=False)
    min_notification_match_score: Mapped[int] = mapped_column(Integer, default=65, nullable=False)
    user = relationship("User", back_populates="settings")


class SavedSearch(TimestampMixin, Base):
    __tablename__ = "saved_searches"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    query: Mapped[str | None] = mapped_column(Text)
    filters: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_saved_search_user_name"), Index("ix_saved_searches_user_active", "user_id", "is_active"))


class ApprovalRequest(TimestampMixin, Base):
    __tablename__ = "approval_requests"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    application_id: Mapped[str | None] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_approval_requests_app_status", "application_id", "status"),)


class ApplicationAttempt(TimestampMixin, Base):
    __tablename__ = "application_attempts"
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    response_code: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("application_id", "attempt_number", name="uq_application_attempt_number"), Index("ix_application_attempts_app", "application_id", "attempt_number"))


class SourceCredential(TimestampMixin, Base):
    __tablename__ = "source_credentials"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_id: Mapped[str] = mapped_column(ForeignKey("job_sources.id", ondelete="CASCADE"), nullable=False)
    secret_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("user_id", "source_id", name="uq_source_credential_user_source"),)


class NotificationPreference(TimestampMixin, Base):
    __tablename__ = "notification_preferences"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    __table_args__ = (UniqueConstraint("user_id", "channel", "event_type", name="uq_notification_preference"),)


class NotificationDeliveryLog(TimestampMixin, Base):
    __tablename__ = "notification_delivery_logs"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    notification_id: Mapped[str | None] = mapped_column(ForeignKey("notifications.id", ondelete="SET NULL"))
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(255))
    content_hash: Mapped[str | None] = mapped_column(String(128))
    recipient: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str | None] = mapped_column(String(255))
    payload_preview: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index("ix_notif_delivery_user_dedupe", "user_id", "event_type", "dedupe_key"),
        Index("ix_notif_delivery_status_retry", "status", "next_retry_at"),
    )


class AIProcessingHistory(TimestampMixin, Base):
    __tablename__ = "ai_processing_history"
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    processor: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    input_hash: Mapped[str | None] = mapped_column(String(128))
    output: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (Index("ix_ai_history_entity", "entity_type", "entity_id"),)


class AuthSession(TimestampMixin, Base):
    __tablename__ = "auth_sessions"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    __table_args__ = (Index("ix_auth_sessions_user_expires", "user_id", "expires_at"),)


class PasswordResetToken(TimestampMixin, Base):
    __tablename__ = "password_reset_tokens"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_password_reset_user_expires", "user_id", "expires_at"),)


class LoginAttempt(TimestampMixin, Base):
    __tablename__ = "login_attempts"
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    __table_args__ = (Index("ix_login_attempts_email_created", "email", "created_at"), Index("ix_login_attempts_ip_created", "ip_address", "created_at"))


class ProfileFact(TimestampMixin, Base):
    __tablename__ = "profile_facts"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    field_key: Mapped[str] = mapped_column(String(120), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="confirmed", nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    evidence_document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_profile_facts_user_field_status", "user_id", "field_key", "status"),)
