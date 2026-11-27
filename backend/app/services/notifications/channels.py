from dataclasses import dataclass
from email.message import EmailMessage
import re
import smtplib
from typing import Any, Callable

import httpx

from app.core.config import settings

_CREDENTIAL_PATTERNS = [
    re.compile(r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|bot[_-]?token|access[_-]?token|refresh[_-]?token|token)\s*[:=]\s*([^\s,;'\"]+)"),
    re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/-]+=*"),
    re.compile(r"https?://[^\s/:@]+:[^\s/@]+@"),
]

_CV_BLOCK_RE = re.compile(
    r"(?is)(?:---+\s*(?:cv|resume|curriculum vitae)\s*---+|\b(?:curriculum vitae|work experience|employment history|education history|references available)\b.*)"
)


def sanitize_notification_text(
    text: str,
    *,
    redact_cv_content: bool = False,
    sensitive_snippets: list[str] | None = None,
    extra_secrets: list[str] | None = None,
) -> str:
    """Strip credentials and optionally CV body contents from outbound notification messages."""
    cleaned = text or ""
    secrets_to_mask = [
        settings.secret_key,
        settings.telegram_bot_token,
        settings.smtp_password,
        settings.ai_api_key,
        *(extra_secrets or []),
    ]
    for secret in secrets_to_mask:
        if secret and len(secret) >= 4:
            cleaned = cleaned.replace(secret, "[REDACTED]")
    for pattern in _CREDENTIAL_PATTERNS:
        if pattern.groups >= 2:
            cleaned = pattern.sub(lambda m: f"{m.group(1)}=[REDACTED]", cleaned)
        else:
            cleaned = pattern.sub("[REDACTED]", cleaned)
    if redact_cv_content:
        for snippet in sensitive_snippets or []:
            normalized = (snippet or "").strip()
            if len(normalized) >= 12:
                cleaned = cleaned.replace(normalized, "[CV CONTENT REDACTED]")
        cleaned = _CV_BLOCK_RE.sub("[CV CONTENT REDACTED]", cleaned)
        cleaned = re.sub(r"\b\d{3}[-.\s]?\d{2,3}[-.\s]?\d{4}\b", "[REDACTED]", cleaned)
    return cleaned.strip()


@dataclass
class DeliveryOutcome:
    delivered: bool
    provider_message_id: str | None = None
    error: str | None = None


class TelegramClient:
    """Telegram Bot API client using httpx."""

    def __init__(
        self,
        bot_token: str | None = None,
        api_base_url: str | None = None,
        http_client: httpx.Client | None = None,
    ):
        self.bot_token = bot_token if bot_token is not None else settings.telegram_bot_token
        self.api_base_url = (api_base_url or settings.telegram_api_base_url).rstrip("/")
        self._http_client = http_client

    def send_message(
        self,
        chat_id: str,
        text: str,
        inline_actions: list[list[dict[str, str]]] | None = None,
    ) -> DeliveryOutcome:
        if not self.bot_token:
            return DeliveryOutcome(False, error="Telegram bot token is not configured")
        if not chat_id:
            return DeliveryOutcome(False, error="Telegram chat ID is not configured")
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if inline_actions:
            payload["reply_markup"] = {"inline_keyboard": inline_actions}
        url = f"{self.api_base_url}/bot{self.bot_token}/sendMessage"
        owns_client = self._http_client is None
        client = self._http_client or httpx.Client(timeout=10.0)
        try:
            response = client.post(url, json=payload)
            if response.status_code >= 400:
                return DeliveryOutcome(False, error=f"Telegram API error: HTTP {response.status_code}")
            body = response.json()
            if not body.get("ok"):
                return DeliveryOutcome(False, error=str(body.get("description") or "Telegram API rejected message"))
            message_id = str((body.get("result") or {}).get("message_id", "")) or None
            return DeliveryOutcome(True, provider_message_id=message_id)
        except Exception as exc:
            return DeliveryOutcome(False, error=sanitize_notification_text(str(exc), extra_secrets=[self.bot_token]))
        finally:
            if owns_client:
                client.close()


class EmailClient:
    """SMTP email client."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        from_email: str | None = None,
        use_tls: bool | None = None,
        smtp_factory: Callable[[str, int], Any] | None = None,
    ):
        self.host = host if host is not None else settings.smtp_host
        self.port = port if port is not None else settings.smtp_port
        self.username = username if username is not None else settings.smtp_username
        self.password = password if password is not None else settings.smtp_password
        self.from_email = from_email or settings.smtp_from_email
        self.use_tls = settings.smtp_use_tls if use_tls is None else use_tls
        self._smtp_factory = smtp_factory or (lambda h, p: smtplib.SMTP(h, p, timeout=10))

    def send_email(self, to_email: str, subject: str, body: str) -> DeliveryOutcome:
        if not self.host:
            return DeliveryOutcome(False, error="SMTP host is not configured")
        if not to_email:
            return DeliveryOutcome(False, error="Recipient email is missing")
        msg = EmailMessage()
        msg["From"] = self.from_email
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body)
        try:
            with self._smtp_factory(self.host, self.port) as server:
                if self.use_tls and hasattr(server, "starttls"):
                    server.starttls()
                if self.username and self.password and hasattr(server, "login"):
                    server.login(self.username, self.password)
                server.send_message(msg)
            return DeliveryOutcome(True, provider_message_id=msg["Message-ID"] or "smtp-sent")
        except Exception as exc:
            return DeliveryOutcome(False, error=sanitize_notification_text(str(exc), extra_secrets=[self.password or ""]))
