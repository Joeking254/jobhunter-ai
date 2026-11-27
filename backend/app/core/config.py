from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    app_name: str = "JOBHUNTER AI"
    app_env: str = "development"
    secret_key: str
    log_level: str = "INFO"
    mysql_host: str = "mysql"
    mysql_port: int = 3306
    mysql_database: str = "jobhunter_db"
    mysql_user: str = "jobhunter_app"
    mysql_password: str
    database_pool_size: int = 5
    database_max_overflow: int = 10
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"
    session_ttl_minutes: int = 60 * 24 * 7
    password_reset_ttl_minutes: int = 30
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_minutes: int = 15
    failed_login_lockout_threshold: int = 10
    failed_login_lockout_minutes: int = 30
    cookie_secure: bool = True
    cookie_domain: str | None = None
    csrf_cookie_name: str = "jobhunter_csrf"
    session_cookie_name: str = "jobhunter_session"
    document_storage_dir: str = "/tmp/jobhunter-documents"
    max_document_size_mb: int = 10
    discovery_request_timeout_seconds: int = 20
    discovery_rate_limit_seconds: float = 1.0
    discovery_max_retries: int = 3
    ai_provider: str = "rules"
    ai_api_url: str | None = None
    ai_api_key: str | None = None
    ai_model: str = "configured-model"
    match_strong_threshold: int = 85
    match_approval_threshold: int = 65
    match_weight_skills: int = 35
    match_weight_education: int = 15
    match_weight_experience: int = 20
    match_weight_location: int = 10
    match_weight_authorization: int = 10
    match_weight_type: int = 5
    match_weight_preference: int = 5
    telegram_bot_token: str | None = None
    telegram_api_base_url: str = "https://api.telegram.org"
    telegram_webhook_secret: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str = "noreply@jobhunter.local"
    smtp_use_tls: bool = True
    notification_max_retries: int = 3
    notification_retry_backoff_seconds: int = 300
    backup_dir: str = "/tmp/jobhunter-backups"
    backup_retention_days: int = 14
    browser_max_concurrency: int = 2

    @model_validator(mode="after")
    def production_security_hardening(self) -> "Settings":
        if self.app_env.lower() == "production":
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true in production")
            if len(self.secret_key) < 32 or "replace-with" in self.secret_key.lower():
                raise ValueError("SECRET_KEY must be a unique strong secret (32+ chars) in production")
            if "replace-with" in self.mysql_password.lower():
                raise ValueError("MYSQL_PASSWORD must not use example placeholder in production")
        return self

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    @property
    def database_url(self) -> URL:
        return URL.create(
            "mysql+pymysql",
            username=self.mysql_user,
            password=self.mysql_password,
            host=self.mysql_host,
            port=self.mysql_port,
            database=self.mysql_database,
            query={"charset": "utf8mb4"},
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
