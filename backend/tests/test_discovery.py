import json

import httpx
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db.base import Base, import_models
from app.models.models import JobSource, Opportunity, SourceExecutionHistory
from app.services.discovery.base import DiscoveryQuery
from app.services.discovery.connectors import AuthorizedCareerPageConnector, GreenhouseConnector, LeverConnector, RSSConnector, RemotiveConnector
from app.services.discovery.runner import run_source

import_models()


def client_for(payload, content_type="json"):
    def handler(request):
        if content_type == "json":
            return httpx.Response(200, json=payload)
        return httpx.Response(200, text=payload)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_greenhouse_and_lever_normalize_and_filter():
    greenhouse = GreenhouseConnector({"board_token": "example", "company": "Example"}, client_for({"jobs": [{"id": 1, "title": "Senior Python Engineer", "location": {"name": "Remote"}, "absolute_url": "https://jobs.example/1", "content": "Build APIs"}]}))
    items = greenhouse.fetch(DiscoveryQuery(keywords=("python",), remote_only=True))
    assert items[0].external_id == "1"
    assert items[0].remote_only is True
    lever = LeverConnector({"site": "example", "company": "Example"}, client_for([{"id": "l1", "text": "Frontend Developer", "categories": {"location": "Nairobi", "team": "Engineering"}, "hostedUrl": "https://jobs.example/l1", "descriptionPlain": "React role"}]))
    assert lever.fetch(DiscoveryQuery(location="Nairobi"))[0].company == "Example"


def test_remotive_rss_and_authorized_page_connectors():
    remotive = RemotiveConnector({}, client_for({"jobs": [{"id": 42, "title": "Data Annotator", "company_name": "Remote Co", "url": "https://remote/42", "candidate_required_location": "Worldwide", "description": "Annotate data", "category": "Data annotation"}]}))
    assert remotive.fetch(DiscoveryQuery(keywords=("annotator",)))[0].remote_only is True
    rss = RSSConnector({"feed_url": "https://feed.test/jobs", "company": "Feed Co"}, client_for("""<rss><channel><item><guid>r1</guid><title>Support Specialist</title><link>https://feed.test/1</link><description>Remote support</description></item></channel></rss>""", "text"))
    assert rss.fetch(DiscoveryQuery(remote_only=True))[0].external_id == "r1"
    html = '<html><article><h2>Research Assistant</h2><a href="https://authorized/jobs/1">Apply</a></article></html>'
    page = AuthorizedCareerPageConnector({"authorized": True, "url": "https://authorized/jobs", "company": "Authorized Co", "selectors": {"item": "article", "title": "h2", "url": "a"}}, client_for(html, "text"))
    assert page.fetch(DiscoveryQuery())[0].title == "Research Assistant"


def test_runner_deduplicates_and_records_history(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'discovery.db'}")
    Base.metadata.create_all(engine)

    class FakeConnector:
        def __init__(self, config):
            self.config = config
        def fetch(self, query):
            from app.services.discovery.base import NormalizedOpportunity
            return [NormalizedOpportunity("job-1", "Engineer", "Example", "https://example/job-1", location="Remote", remote_only=True)]
        def close(self):
            pass

    from app.services.discovery import runner
    monkeypatch.setitem(runner.CONNECTOR_TYPES, "fake", FakeConnector)
    with Session(engine) as db:
        source = JobSource(name="Fake", base_url="https://example", connector_type="fake", config_json=json.dumps({}))
        db.add(source)
        db.commit()
        first = run_source(db, source)
        second = run_source(db, source)
        assert first.status == "success"
        assert first.created_count == 1
        assert second.created_count == 0
        assert db.scalar(select(func.count(Opportunity.id))) == 1
        assert db.scalar(select(func.count(SourceExecutionHistory.id))) == 2
