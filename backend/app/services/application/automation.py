from dataclasses import dataclass, field
from pathlib import Path
import re
import threading
from typing import Any
from uuid import uuid4

from bs4 import BeautifulSoup

from app.core.config import settings

_BROWSER_SEM_LOCK = threading.Lock()
_BROWSER_SEM_LIMIT: int | None = None
_BROWSER_SEMAPHORE: threading.BoundedSemaphore | None = None


def get_browser_semaphore() -> threading.BoundedSemaphore:
    global _BROWSER_SEM_LIMIT, _BROWSER_SEMAPHORE
    limit = max(1, int(settings.browser_max_concurrency))
    with _BROWSER_SEM_LOCK:
        if _BROWSER_SEMAPHORE is None or _BROWSER_SEM_LIMIT != limit:
            _BROWSER_SEM_LIMIT = limit
            _BROWSER_SEMAPHORE = threading.BoundedSemaphore(limit)
        return _BROWSER_SEMAPHORE


@dataclass
class FormField:
    name: str
    label: str
    field_type: str = "text"
    required: bool = False
    selector: str | None = None
    options: list[str] = field(default_factory=list)


@dataclass
class FormDetection:
    fields: list[FormField]
    requires_manual_intervention: bool = False
    reason: str | None = None
    form_found: bool = True
    logs: list[str] = field(default_factory=list)


@dataclass
class SubmissionResult:
    status: str
    confirmation_reference: str | None = None
    error: str | None = None
    screenshot_path: str | None = None
    logs: list[str] = field(default_factory=list)


_ALIAS_GROUPS: list[set[str]] = [
    {"email", "email address", "e mail", "work email", "candidate email"},
    {"first name", "given name", "fname", "first"},
    {"last name", "surname", "family name", "lname", "last"},
    {"full name", "name", "candidate name", "applicant name"},
    {"phone", "phone number", "telephone", "mobile", "contact number"},
    {"city", "location", "current city"},
    {"country", "nation"},
    {"linkedin", "linkedin url", "linkedin profile"},
    {"portfolio", "portfolio url", "website", "github"},
    {"work authorization", "authorized", "visa", "sponsorship", "work permit"},
]

_CAPTCHA_MFA_RE = re.compile(
    r"captcha|recaptcha|hcaptcha|turnstile|two-factor|multi-factor|\bmfa\b|\botp\b|verification code|verify you are human|sign in to apply|log in to apply",
    re.IGNORECASE,
)
_FEE_PAYMENT_RE = re.compile(
    r"application fee|processing fee|pay now|payment required|credit card|debit card|billing address|checkout|\$\s*\d+(?:\.\d{2})?\s*(?:fee|charge)",
    re.IGNORECASE,
)
_CONFIRMATION_REF_RE = re.compile(
    r"(?:confirmation(?:\s*(?:id|code|number|ref(?:erence)?))?|reference(?:\s*(?:id|code|number))?|application\s*(?:id|number)|tracking\s*(?:id|number|code)|ref(?:\s*(?:id|number))?)[:#\s]+([A-Za-z0-9][A-Za-z0-9-]{2,})",
    re.IGNORECASE,
)
_CONFIRMATION_TEXT_RE = re.compile(
    r"thank you for applying|application (?:has been )?(?:received|submitted)|successfully submitted|we have received your application",
    re.IGNORECASE,
)
_VALIDATION_ERROR_RE = re.compile(
    r"(?:validation (?:error|failed)|is required|required field|invalid (?:email|phone|input|url|format)|please (?:enter|provide|fix|complete)|cannot be blank|submission failed|must be a valid)",
    re.IGNORECASE,
)


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def identify_field_value(field: FormField, values: dict[str, str]) -> str | None:
    """Match a form field against verified candidate/application answers without fabricating."""
    normalized_map = {_norm(k): v for k, v in values.items() if k and v is not None}
    candidates = [_norm(field.label), _norm(field.name)]
    for candidate in candidates:
        if candidate and candidate in normalized_map:
            return normalized_map[candidate]
    for candidate in candidates:
        if not candidate:
            continue
        for key, answer in normalized_map.items():
            if key and (key in candidate or candidate in key):
                return answer
    for group in _ALIAS_GROUPS:
        if any(candidate in group or any(alias in candidate for alias in group) for candidate in candidates if candidate):
            for key, answer in normalized_map.items():
                if key in group or any(alias in key for alias in group):
                    return answer
    return None


def is_cv_file_field(field: FormField) -> bool:
    combined = f"{field.label} {field.name}".lower()
    if "cover" in combined:
        return False
    return any(term in combined for term in ("cv", "resume", "curriculum"))


def is_cover_letter_file_field(field: FormField) -> bool:
    combined = f"{field.label} {field.name}".lower()
    return "cover" in combined or "letter" in combined


def detect_manual_gate_from_html(html: str, body_text: str) -> str | None:
    """Detect CAPTCHA, MFA/login walls, or payment/application fees that must pause automation."""
    soup = BeautifulSoup(html or "", "html.parser")
    if soup.select("iframe[src*='recaptcha'], iframe[src*='hcaptcha'], iframe[src*='turnstile'], .g-recaptcha, .h-captcha, .cf-turnstile, [data-sitekey]"):
        return "CAPTCHA widget detected; manual intervention required"
    if soup.select("input[type='password']"):
        return "Login or password authentication required; manual intervention required"
    if soup.select("iframe[src*='stripe'], input[name*='card'], input[autocomplete='cc-number']"):
        return "Payment or application fee gate detected; never pay application fees"
    if _CAPTCHA_MFA_RE.search(body_text or ""):
        return "CAPTCHA or MFA requires manual intervention"
    if _FEE_PAYMENT_RE.search(body_text or ""):
        return "Application fee or payment detected; never pay application fees"
    return None


def extract_confirmation_reference(body_text: str) -> str | None:
    match = _CONFIRMATION_REF_RE.search(body_text or "")
    return match.group(1) if match else None


def is_confirmation_present(body_text: str) -> bool:
    return bool(extract_confirmation_reference(body_text) or _CONFIRMATION_TEXT_RE.search(body_text or ""))


def detect_validation_errors(body_text: str, error_elements_text: list[str] | None = None, html5_invalid_messages: list[str] | None = None) -> str | None:
    errors: list[str] = []
    for msg in html5_invalid_messages or []:
        cleaned = (msg or "").strip()
        if cleaned:
            errors.append(cleaned)
    for msg in error_elements_text or []:
        cleaned = (msg or "").strip()
        if cleaned:
            errors.append(cleaned)
    if not errors and _VALIDATION_ERROR_RE.search(body_text or ""):
        match = _VALIDATION_ERROR_RE.search(body_text or "")
        if match:
            errors.append(match.group(0))
    if not errors:
        return None
    deduped = list(dict.fromkeys(errors))
    return "; ".join(deduped)[:2000]


def missing_required_fields(fields: list[FormField], answers: dict[str, str], cv_path: str, cover_letter_path: str) -> list[str]:
    missing: list[str] = []
    for field in fields:
        if not field.required:
            continue
        if field.field_type == "file":
            target = cv_path if is_cv_file_field(field) else cover_letter_path
            if not target or not Path(target).is_file():
                missing.append(field.label or field.name)
        else:
            value = identify_field_value(field, answers)
            if value is None or not str(value).strip():
                missing.append(field.label or field.name)
    return missing


class BrowserAdapter:
    def detect_form(self, url: str) -> FormDetection:
        raise NotImplementedError

    def fill_form(self, fields: list[FormField], answers: dict[str, str], cv_path: str, cover_letter_path: str) -> None:
        raise NotImplementedError

    def submit(self, screenshot_name: str | None = None) -> SubmissionResult:
        raise NotImplementedError


class PlaywrightBrowserAdapter(BrowserAdapter):
    """Playwright adapter for permitted workflows; manages isolated browser contexts and never bypasses CAPTCHA/MFA or pays fees."""

    def __init__(
        self,
        screenshot_dir: Path,
        *,
        headless: bool = True,
        timeout_ms: int = 15000,
        storage_state: dict[str, Any] | str | None = None,
        playwright_factory: Any = None,
    ):
        self.screenshot_dir = Path(screenshot_dir)
        self.timeout_ms = timeout_ms
        self.logs: list[str] = []
        self._semaphore = get_browser_semaphore()
        self._semaphore_acquired = self._semaphore.acquire(timeout=max(5.0, timeout_ms / 1000.0))
        if not self._semaphore_acquired:
            raise RuntimeError("Browser concurrency limit reached; try again shortly")
        self._playwright = None
        self.browser = None
        self.context = None
        self.page = None
        try:
            if playwright_factory is None:
                from playwright.sync_api import sync_playwright
                playwright_factory = sync_playwright
            self._playwright = playwright_factory().start()
            self.browser = self._playwright.chromium.launch(headless=headless)
            context_kwargs: dict[str, Any] = {}
            if storage_state is not None:
                context_kwargs["storage_state"] = storage_state
            self.context = self.browser.new_context(**context_kwargs)
            self.page = self.context.new_page()
            if hasattr(self.page, "set_default_timeout"):
                self.page.set_default_timeout(timeout_ms)
            self.logs.append("Browser session initialized")
        except Exception:
            self.close()
            raise

    def __enter__(self) -> "PlaywrightBrowserAdapter":
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()

    def _capture_screenshot(self, filename: str) -> str:
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        path = self.screenshot_dir / filename
        self.page.screenshot(path=str(path), full_page=True)
        self.logs.append(f"Captured audit screenshot: {path.name}")
        return str(path)

    def _resolve_label(self, element: Any, html_soup: BeautifulSoup, name: str, el_id: str | None) -> str:
        aria = element.get_attribute("aria-label")
        if aria and aria.strip():
            return aria.strip()
        if el_id:
            label_tag = html_soup.find("label", attrs={"for": el_id})
            if label_tag and label_tag.get_text(strip=True):
                return label_tag.get_text(" ", strip=True)
        placeholder = element.get_attribute("placeholder")
        if placeholder and placeholder.strip():
            return placeholder.strip()
        return name

    def detect_form(self, url: str) -> FormDetection:
        self.logs.append(f"Navigating to application URL: {url}")
        self.page.goto(url, wait_until="domcontentloaded")
        html = self.page.content() if hasattr(self.page, "content") else ""
        body = self.page.locator("body").inner_text()
        manual_reason = detect_manual_gate_from_html(html, body)
        if manual_reason:
            self.logs.append(f"Paused: {manual_reason}")
            return FormDetection([], True, manual_reason, form_found=False, logs=list(self.logs))

        soup = BeautifulSoup(html or "", "html.parser")
        fields: list[FormField] = []
        seen_selectors: set[str] = set()
        for element in self.page.locator("form input, form textarea, form select, input, textarea, select").all():
            tag_name = (element.evaluate("el => el.tagName.toLowerCase()") if hasattr(element, "evaluate") else "input") or "input"
            raw_type = (element.get_attribute("type") or "").lower()
            if tag_name == "select":
                field_type = "select"
            elif tag_name == "textarea":
                field_type = "textarea"
            else:
                field_type = raw_type or "text"
            if field_type in {"hidden", "submit", "button", "reset", "image"}:
                continue
            attr_name = element.get_attribute("name")
            attr_id = element.get_attribute("id")
            name = attr_name or attr_id or f"field_{len(fields) + 1}"
            selector = f"[name='{attr_name}']" if attr_name else (f"#{attr_id}" if attr_id else None)
            if selector and selector in seen_selectors:
                continue
            if selector:
                seen_selectors.add(selector)
            label = self._resolve_label(element, soup, name, attr_id)
            required = element.get_attribute("required") is not None or element.get_attribute("aria-required") == "true"
            options: list[str] = []
            if field_type == "select":
                select_node = soup.find("select", attrs={"name": attr_name} if attr_name else {"id": attr_id})
                if select_node:
                    options = [opt.get_text(" ", strip=True) for opt in select_node.find_all("option") if opt.get_text(strip=True)]
            fields.append(FormField(name=name, label=label, field_type=field_type, required=required, selector=selector, options=options))

        if not fields:
            reason = "No fillable application form detected"
            self.logs.append(reason)
            return FormDetection([], True, reason, form_found=False, logs=list(self.logs))

        self.logs.append(f"Detected {len(fields)} form field(s)")
        return FormDetection(fields, form_found=True, logs=list(self.logs))

    def fill_form(self, fields: list[FormField], answers: dict[str, str], cv_path: str, cover_letter_path: str) -> None:
        for field in fields:
            selector = field.selector or f"[name='{field.name}']"
            locator = self.page.locator(selector).first
            if field.field_type == "file":
                target_path = cv_path if is_cv_file_field(field) else cover_letter_path
                if not target_path or not Path(target_path).is_file():
                    raise FileNotFoundError(f"Required attachment not found on disk: {target_path}")
                locator.set_input_files(target_path)
                self.logs.append(f"Attached file for field '{field.label}': {Path(target_path).name}")
                continue
            value = identify_field_value(field, answers)
            if value is None:
                continue
            if field.field_type == "select":
                locator.select_option(label=value) if value in field.options else locator.select_option(value)
            elif field.field_type == "checkbox":
                if str(value).strip().lower() in {"true", "yes", "1", "on", "checked"}:
                    locator.check()
                else:
                    locator.uncheck()
            elif field.field_type == "radio":
                self.page.locator(f"{selector}[value='{value}']").first.check()
            else:
                locator.fill(str(value))
            self.logs.append(f"Populated field '{field.label}'")

    def submit(self, screenshot_name: str | None = None) -> SubmissionResult:
        submit_locator = self.page.locator("button[type='submit'], input[type='submit']")
        if submit_locator.count() == 0:
            screenshot = self._capture_screenshot(screenshot_name or f"missing-submit-{uuid4().hex[:8]}.png")
            return SubmissionResult("failed", error="Submit button not found on application form", screenshot_path=screenshot, logs=list(self.logs))

        self.logs.append("Clicking application submit control")
        submit_locator.first.click()
        if hasattr(self.page, "wait_for_load_state"):
            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=3000)
            except Exception:
                pass

        body = self.page.locator("body").inner_text()
        error_texts: list[str] = []
        for selector in (".error", ".invalid-feedback", ".field-error", "[role='alert']", "[aria-invalid='true']"):
            for node in self.page.locator(selector).all():
                txt = node.inner_text().strip()
                if txt:
                    error_texts.append(txt)
        html5_invalid: list[str] = []
        if hasattr(self.page, "evaluate"):
            try:
                html5_invalid = self.page.evaluate(
                    "() => Array.from(document.querySelectorAll(':invalid')).map(el => el.validationMessage).filter(Boolean)"
                ) or []
            except Exception:
                html5_invalid = []

        screenshot = self._capture_screenshot(screenshot_name or f"submission-{uuid4().hex[:8]}.png")
        validation_error = detect_validation_errors(body, error_texts, html5_invalid)
        if validation_error:
            self.logs.append(f"Validation error detected: {validation_error}")
            return SubmissionResult("failed", error=validation_error, screenshot_path=screenshot, logs=list(self.logs))

        reference = extract_confirmation_reference(body)
        if is_confirmation_present(body):
            self.logs.append(f"Submission confirmed (reference={reference})")
            return SubmissionResult("submitted", reference, screenshot_path=screenshot, logs=list(self.logs))

        self.logs.append("Submission state unclear; awaiting confirmation")
        return SubmissionResult("confirmation_pending", screenshot_path=screenshot, logs=list(self.logs))

    def close(self) -> None:
        try:
            for obj in (self.context, self.browser):
                if obj is not None:
                    try:
                        obj.close()
                    except Exception:
                        pass
            if self._playwright is not None:
                try:
                    self._playwright.stop()
                except Exception:
                    pass
        finally:
            if getattr(self, "_semaphore_acquired", False):
                self._semaphore_acquired = False
                try:
                    self._semaphore.release()
                except ValueError:
                    pass
