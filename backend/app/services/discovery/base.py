from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import re
from typing import Any

import httpx

from app.core.config import settings

CATEGORIES = [
    "IT", "Software development", "Web development", "Cybersecurity", "Networking", "Technical support", "Artificial intelligence", "Machine learning", "LLM evaluation", "Data annotation", "Data entry", "Research", "Graphic design", "Digital marketing", "Customer service", "Virtual assistance", "Internships", "Industrial attachment", "Graduate programmes", "Freelancing", "Contract work", "Scholarships", "Training programmes",
]


@dataclass(frozen=True)
class DiscoveryQuery:
    keywords: tuple[str, ...] = ()
    location: str | None = None
    remote_only: bool = False
    categories: tuple[str, ...] = ()
    page: int = 1
    page_size: int = 100


@dataclass
class NormalizedOpportunity:
    external_id: str
    title: str
    company: str
    url: str
    description: str | None = None
    location: str | None = None
    posted_at: datetime | None = None
    deadline: datetime | None = None
    experience_requirements: str | None = None
    salary_text: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    remote_only: bool = False
    categories: list[str] = field(default_factory=list)
    dedupe_hash: str = ""

    def __post_init__(self) -> None:
        if not self.dedupe_hash:
            value = "|".join((self.company, self.title, self.location or "", self.url.split("?")[0])).lower()
            self.dedupe_hash = hashlib.sha256(re.sub(r"\s+", " ", value).strip().encode()).hexdigest()


class BaseConnector(ABC):
    name: str
    connector_type: str

    def __init__(self, config: dict[str, Any] | None = None, client: httpx.Client | None = None) -> None:
        self.config = config or {}
        self.client = client or httpx.Client(timeout=settings.discovery_request_timeout_seconds, follow_redirects=True)

    @abstractmethod
    def fetch(self, query: DiscoveryQuery) -> list[NormalizedOpportunity]:
        """Fetch and normalize public or explicitly authorized opportunities."""

    def close(self) -> None:
        self.client.close()

    def _get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        last_error: Exception | None = None
        for attempt in range(settings.discovery_max_retries):
            try:
                response = self.client.get(url, params=params, headers={"User-Agent": "JOBHUNTER-AI opportunity discovery"})
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt + 1 < settings.discovery_max_retries:
                    import time
                    time.sleep(settings.discovery_rate_limit_seconds * (attempt + 1))
        raise RuntimeError(f"Source request failed: {url}") from last_error

    def _get_text(self, url: str) -> str:
        response = self.client.get(url, headers={"User-Agent": "JOBHUNTER-AI opportunity discovery"})
        response.raise_for_status()
        return response.text


def matches_query(item: NormalizedOpportunity, query: DiscoveryQuery) -> bool:
    haystack = " ".join((item.title, item.company, item.description or "", item.location or "")).lower()
    if query.keywords and not all(keyword.lower() in haystack for keyword in query.keywords):
        return False
    if query.location and query.location.lower() not in (item.location or "").lower():
        return False
    if query.remote_only and not item.remote_only:
        return False
    if query.categories and not set(query.categories).intersection(item.categories):
        return False
    return True
