from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
from bs4 import BeautifulSoup

from app.services.discovery.base import BaseConnector, DiscoveryQuery, NormalizedOpportunity, matches_query


def _date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        try:
            return parsedate_to_datetime(str(value))
        except (TypeError, ValueError):
            return None


def _remote(location: str | None, description: str | None) -> bool:
    text = f"{location or ''} {description or ''}".lower()
    return any(term in text for term in ("remote", "work from home", "anywhere"))


class GreenhouseConnector(BaseConnector):
    name = "Greenhouse public job board"
    connector_type = "greenhouse"

    def fetch(self, query: DiscoveryQuery) -> list[NormalizedOpportunity]:
        token = self.config["board_token"]
        data = self._get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", {"content": "true"})
        results = []
        for raw in data.get("jobs", []):
            location = (raw.get("location") or {}).get("name")
            item = NormalizedOpportunity(str(raw["id"]), raw.get("title", "Untitled"), self.config.get("company", token), raw.get("absolute_url", ""), raw.get("content"), location, _date(raw.get("updated_at")), remote_only=_remote(location, raw.get("content")))
            if matches_query(item, query):
                results.append(item)
        return results


class LeverConnector(BaseConnector):
    name = "Lever public postings"
    connector_type = "lever"

    def fetch(self, query: DiscoveryQuery) -> list[NormalizedOpportunity]:
        site = self.config["site"]
        data = self._get_json(f"https://api.lever.co/v0/postings/{site}", {"mode": "json"})
        results = []
        for raw in data:
            categories = [raw.get("categories", {}).get("team", ""), raw.get("categories", {}).get("commitment", "")]
            location = raw.get("categories", {}).get("location")
            description = raw.get("descriptionPlain") or raw.get("description")
            item = NormalizedOpportunity(str(raw.get("id")), raw.get("text", "Untitled"), self.config.get("company", site), raw.get("hostedUrl") or raw.get("applyUrl", ""), description, location, _date(raw.get("createdAt")), remote_only=_remote(location, description), categories=[x for x in categories if x])
            if matches_query(item, query):
                results.append(item)
        return results


class RemotiveConnector(BaseConnector):
    name = "Remotive"
    connector_type = "remotive"

    def fetch(self, query: DiscoveryQuery) -> list[NormalizedOpportunity]:
        data = self._get_json("https://remotive.com/api/remote-jobs", {"search": " ".join(query.keywords), "limit": query.page_size, "page": query.page})
        results = []
        for raw in data.get("jobs", []):
            location = raw.get("candidate_required_location")
            description = raw.get("description")
            item = NormalizedOpportunity(str(raw.get("id")), raw.get("title", "Untitled"), raw.get("company_name", "Unknown"), raw.get("url", ""), description, location, _date(raw.get("publication_date")), _date(raw.get("deadline")), salary_text=raw.get("salary"), remote_only=True, categories=raw.get("category", "").split(",") if raw.get("category") else [])
            if matches_query(item, query):
                results.append(item)
        return results


class RSSConnector(BaseConnector):
    name = "RSS feed"
    connector_type = "rss"

    def fetch(self, query: DiscoveryQuery) -> list[NormalizedOpportunity]:
        parsed = feedparser.parse(self._get_text(self.config["feed_url"]))
        results = []
        for raw in parsed.entries:
            description = raw.get("summary") or raw.get("description")
            location = raw.get("location") or self.config.get("location")
            item = NormalizedOpportunity(raw.get("id") or raw.get("link", ""), raw.get("title", "Untitled"), self.config.get("company", self.config.get("feed_url", "RSS source")), raw.get("link", ""), description, location, _date(raw.get("published")), remote_only=_remote(location, description), categories=list(self.config.get("categories", [])))
            if matches_query(item, query):
                results.append(item)
        return results


class AuthorizedCareerPageConnector(BaseConnector):
    name = "Authorized company career page"
    connector_type = "authorized_career_page"

    def fetch(self, query: DiscoveryQuery) -> list[NormalizedOpportunity]:
        if not self.config.get("authorized"):
            raise PermissionError("Career page connector requires explicit authorization")
        soup = BeautifulSoup(self._get_text(self.config["url"]), "html.parser")
        selectors = self.config.get("selectors", {})
        results = []
        for card in soup.select(selectors.get("item", "article")):
            title_node = card.select_one(selectors.get("title", "h2"))
            link_node = card.select_one(selectors.get("url", "a"))
            if not title_node or not link_node or not link_node.get("href"):
                continue
            url = link_node["href"]
            item = NormalizedOpportunity(url, title_node.get_text(" ", strip=True), self.config.get("company", "Authorized company"), url, card.get_text(" ", strip=True), self.config.get("location"), remote_only=_remote(self.config.get("location"), card.get_text(" ", strip=True)), categories=list(self.config.get("categories", [])))
            if matches_query(item, query):
                results.append(item)
        return results


CONNECTOR_TYPES = {"greenhouse": GreenhouseConnector, "lever": LeverConnector, "remotive": RemotiveConnector, "rss": RSSConnector, "authorized_career_page": AuthorizedCareerPageConnector}
FUTURE_CONNECTORS = {"brightermonday", "fuzu", "myjobmag", "linkedin", "indeed", "wellfound", "remote_ok"}
