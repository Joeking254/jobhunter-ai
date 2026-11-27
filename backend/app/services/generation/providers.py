from abc import ABC, abstractmethod
import json
from typing import Any

import httpx

from app.core.config import settings


class GenerationProvider(ABC):
    @abstractmethod
    def generate(self, context: dict[str, Any]) -> dict[str, str | dict[str, str]]:
        """Generate only claims supported by the verified context."""


class VerifiedTemplateProvider(GenerationProvider):
    def generate(self, context: dict[str, Any]) -> dict[str, str | dict[str, str]]:
        job = context["job"]
        profile = context["profile"]
        skills = ", ".join(profile["skills"]) or "the skills documented in my verified profile"
        experience = "; ".join(f"{item['title']} at {item['company']}" for item in profile["experience"])
        education = "; ".join(filter(None, (item.get("qualification") or item.get("degree") for item in profile["education"])))
        cv = "\n".join(filter(None, [f"{profile['first_name']} {profile['last_name']}", profile["email"], profile.get("phone"), profile.get("city"), "", profile.get("professional_summary"), "", "SKILLS", skills, "", "EXPERIENCE", experience, "", "EDUCATION", education]))
        letter = f"Dear Hiring Team,\n\nI am writing to apply for the {job['title']} opportunity at {job['company']}. {profile.get('professional_summary') or 'My verified career profile reflects relevant preparation for this opportunity.'}\n\nMy verified skills include {skills}."
        if experience:
            letter += f" My verified experience includes {experience}."
        letter += "\n\nI would welcome the opportunity to discuss how my documented background aligns with the role.\n\nSincerely,\n" + f"{profile['first_name']} {profile['last_name']}"
        answers = {}
        for question in context.get("questions", []):
            lower = question.lower()
            if "skill" in lower:
                answers[question] = skills
            elif "experience" in lower or "background" in lower:
                answers[question] = experience or "My verified profile does not contain a directly matching employment record yet."
            elif "education" in lower or "qualification" in lower:
                answers[question] = education or "My verified profile does not contain an education record for this question."
            elif "salary" in lower:
                answers[question] = "I am open to discussing compensation in line with the role and its responsibilities."
            else:
                answers[question] = profile.get("professional_summary") or "Please refer to my attached verified profile documents."
        return {"cv": cv, "cover_letter": letter, "answers": answers}


class ExternalGenerationProvider(GenerationProvider):
    def generate(self, context: dict[str, Any]) -> dict[str, str | dict[str, str]]:
        prompt = "Generate a tailored CV, cover letter, and application answers. Use only verified_profile facts; do not invent claims, dates, employers, qualifications, or achievements. Return JSON with cv, cover_letter, answers.\n" + json.dumps(context)
        response = httpx.post(settings.ai_api_url, headers={"Authorization": f"Bearer {settings.ai_api_key}"}, json={"model": settings.ai_model, "messages": [{"role": "user", "content": prompt}], "response_format": {"type": "json_object"}}, timeout=settings.discovery_request_timeout_seconds)
        response.raise_for_status()
        content = response.json().get("choices", [{}])[0].get("message", {}).get("content", "{}")
        return json.loads(content) if isinstance(content, str) else content


def get_generation_provider() -> GenerationProvider:
    if settings.ai_provider == "openai_compatible" and settings.ai_api_url and settings.ai_api_key:
        return ExternalGenerationProvider()
    return VerifiedTemplateProvider()
