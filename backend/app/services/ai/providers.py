from abc import ABC, abstractmethod
import json
from typing import Any

import httpx

from app.core.config import settings


class AIProvider(ABC):
    name = "base"

    @abstractmethod
    def analyze_job(self, job: dict[str, Any]) -> dict[str, Any]:
        """Return structured job analysis JSON without applying candidate-specific scoring."""


class RuleBasedProvider(AIProvider):
    name = "rules"
    skill_terms = ("python", "javascript", "typescript", "react", "sql", "aws", "docker", "kubernetes", "linux", "cybersecurity", "machine learning", "llm", "data analysis", "figma", "customer service", "excel")

    def analyze_job(self, job: dict[str, Any]) -> dict[str, Any]:
        text = " ".join(str(job.get(key) or "") for key in ("title", "description", "experience_requirements")).lower()
        required = [term for term in self.skill_terms if term in text]
        categories = []
        category_map = {"software": "Software development", "web": "Web development", "cyber": "Cybersecurity", "machine learning": "Machine learning", "llm": "LLM evaluation", "data entry": "Data entry", "design": "Graphic design", "marketing": "Digital marketing", "support": "Technical support", "intern": "Internships", "research": "Research"}
        for term, category in category_map.items():
            if term in text:
                categories.append(category)
        if not categories:
            categories = ["IT"]
        import re
        experience = re.search(r"(\d+)\+?\s+years?", text)
        restrictions = []
        if "authorized to work" in text or "work authorization" in text or "visa sponsorship" in text:
            restrictions.append("Work authorization requirement stated in job description")
        risk_warnings = [term for term in ("pay a fee", "wire money", "crypto payment", "guaranteed income", "send your password") if term in text]
        return {"job_category": categories[0], "required_skills": required, "education_requirements": [], "eligibility_restrictions": restrictions, "experience_requirements": f"{experience.group(1)}+ years" if experience else job.get("experience_requirements"), "risk_warnings": risk_warnings, "risk_level": "high" if risk_warnings else "low", "salary": {"text": job.get("salary_text"), "min": job.get("salary_min"), "max": job.get("salary_max"), "currency": job.get("salary_currency")}}


class OpenAICompatibleProvider(AIProvider):
    name = "openai_compatible"

    def __init__(self, url: str, api_key: str, model: str) -> None:
        self.url = url
        self.api_key = api_key
        self.model = model

    def analyze_job(self, job: dict[str, Any]) -> dict[str, Any]:
        prompt = "Analyze this job and return only JSON with job_category, required_skills, education_requirements, eligibility_restrictions, experience_requirements, risk_warnings, risk_level, and salary. Do not invent facts.\n" + json.dumps(job)
        response = httpx.post(self.url, headers={"Authorization": f"Bearer {self.api_key}"}, json={"model": self.model, "messages": [{"role": "user", "content": prompt}], "response_format": {"type": "json_object"}}, timeout=settings.ai_request_timeout_seconds)
        response.raise_for_status()
        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        return json.loads(content) if isinstance(content, str) else content


DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"


def resolved_ai_model(provider: str | None = None, model: str | None = None) -> str:
    """Resolve the effective model name for the configured AI provider."""
    active_provider = (provider if provider is not None else settings.ai_provider).lower()
    configured = (model if model is not None else settings.ai_model).strip()
    if active_provider == "gemini" and (not configured or configured == "configured-model"):
        return DEFAULT_GEMINI_MODEL
    return configured or "configured-model"


def _parse_json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "{}").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    parsed = json.loads(text or "{}")
    if not isinstance(parsed, dict):
        raise ValueError("AI provider returned non-object JSON")
    return parsed


def post_gemini_json(prompt: str, api_key: str, model: str | None = None, api_url: str | None = None) -> dict[str, Any]:
    """Call Gemini generateContent (AI Studio or Vertex Express) and parse JSON."""
    resolved_model = resolved_ai_model("gemini", model)
    endpoints = (
        [api_url]
        if api_url
        else [
            f"https://generativelanguage.googleapis.com/v1beta/models/{resolved_model}:generateContent",
            *(
                [f"https://aiplatform.googleapis.com/v1/publishers/google/models/{resolved_model}:generateContent"]
                if api_key.startswith("AQ.")
                else []
            ),
        ]
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    response: httpx.Response | None = None
    for idx, endpoint in enumerate(endpoints):
        response = httpx.post(
            endpoint,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=settings.ai_request_timeout_seconds,
        )
        if response.status_code not in (401, 403) or idx == len(endpoints) - 1:
            break
    assert response is not None
    response.raise_for_status()
    data = response.json()
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    content = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
    return _parse_json_object(content)


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str | None = None, url: str | None = None) -> None:
        self.api_key = api_key
        self.model = resolved_ai_model("gemini", model)
        self.url = url or None

    def analyze_job(self, job: dict[str, Any]) -> dict[str, Any]:
        prompt = "Analyze this job and return only JSON with job_category, required_skills, education_requirements, eligibility_restrictions, experience_requirements, risk_warnings, risk_level, and salary. Do not invent facts.\n" + json.dumps(job)
        return post_gemini_json(prompt, self.api_key, self.model, self.url)


def get_provider() -> AIProvider:
    provider = settings.ai_provider.lower()
    if provider == "gemini" and settings.ai_api_key:
        return GeminiProvider(settings.ai_api_key, settings.ai_model, settings.ai_api_url)
    if provider == "openai_compatible" and settings.ai_api_url and settings.ai_api_key:
        return OpenAICompatibleProvider(settings.ai_api_url, settings.ai_api_key, settings.ai_model)
    return RuleBasedProvider()
