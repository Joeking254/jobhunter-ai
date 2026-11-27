import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Application, JobSource, Opportunity, SourceExecutionHistory
from app.services.discovery.base import DiscoveryQuery, NormalizedOpportunity
from app.services.discovery.connectors import CONNECTOR_TYPES
from app.worker.control import enforce_source_rate_limit

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _upsert(db: Session, source: JobSource, item: NormalizedOpportunity, now: datetime) -> tuple[bool, bool]:
    existing = db.scalar(select(Opportunity).where(Opportunity.source_id == source.id, Opportunity.external_id == item.external_id))
    if existing is None:
        duplicate = db.scalar(select(Opportunity).where(Opportunity.dedupe_hash == item.dedupe_hash))
        if duplicate is not None:
            duplicate.last_seen_at = now
            return False, True
        existing = Opportunity(source_id=source.id, external_id=item.external_id, dedupe_hash=item.dedupe_hash)
        db.add(existing)
        created = True
    else:
        created = False
    for field in ("title", "company", "url", "description", "location", "posted_at", "deadline", "experience_requirements", "salary_text", "salary_min", "salary_max", "salary_currency", "remote_only"):
        setattr(existing, field, getattr(item, field))
    existing.categories = json.dumps(item.categories)
    existing.last_seen_at = now
    existing.expired_at = None
    if created:
        db.flush()
    return created, False


def run_source(db: Session, source: JobSource, query: DiscoveryQuery | None = None) -> SourceExecutionHistory:
    query = query or DiscoveryQuery()
    history = SourceExecutionHistory(source_id=source.id, status="running", started_at=_now())
    db.add(history)
    db.commit()
    connector_class = CONNECTOR_TYPES.get(source.connector_type)
    if connector_class is None:
        history.status = "failed"
        history.error_message = f"Unsupported connector type: {source.connector_type}"
        history.finished_at = _now()
        db.commit()
        return history
    connector = None
    try:
        enforce_source_rate_limit(source)
        connector = connector_class(json.loads(source.config_json or "{}"))
        items = connector.fetch(query)
        created_count = 0
        duplicate_count = 0
        seen_in_batch: set[tuple[str, str]] = set()
        now = _now()
        for item in items:
            batch_key = (item.external_id, item.dedupe_hash)
            if batch_key in seen_in_batch or any(item.dedupe_hash == h for _, h in seen_in_batch):
                duplicate_count += 1
                continue
            seen_in_batch.add(batch_key)
            created, duplicate = _upsert(db, source, item, now)
            created_count += int(created)
            duplicate_count += int(duplicate)
        history.status = "success"
        history.finished_at = _now()
        history.fetched_count = len(items)
        history.created_count = created_count
        history.updated_count = len(items) - created_count - duplicate_count
        history.pages_fetched = max(1, query.page)
        source.last_success_at = history.finished_at
        source.reliability_score = min(100, source.reliability_score + 1)
        db.commit()
    except Exception as exc:
        logger.exception("Discovery source failed", extra={"source": source.name})
        db.rollback()
        history = db.get(SourceExecutionHistory, history.id) or history
        source = db.get(JobSource, source.id) or source
        history.status = "failed"
        history.finished_at = _now()
        history.error_message = str(exc)[:2000]
        source.reliability_score = max(0, source.reliability_score - 5)
        db.commit()
    finally:
        if connector:
            connector.close()
    return history


def expire_stale_opportunities(db: Session, source_id: str | None = None, seen_before: datetime | None = None) -> int:
    now = _now()
    expired_count = 0
    if source_id is not None and seen_before is not None:
        stale = list(db.scalars(select(Opportunity).where(Opportunity.source_id == source_id, Opportunity.last_seen_at < seen_before, Opportunity.expired_at.is_(None))))
        for opportunity in stale:
            opportunity.expired_at = now
            expired_count += 1
    active_with_deadlines = list(db.scalars(select(Opportunity).where(Opportunity.expired_at.is_(None), Opportunity.deadline.is_not(None))))
    for opportunity in active_with_deadlines:
        dl = opportunity.deadline.astimezone(timezone.utc) if opportunity.deadline.tzinfo else opportunity.deadline.replace(tzinfo=timezone.utc)
        if dl < now:
            opportunity.expired_at = now
            expired_count += 1
    expired_ids = [opp.id for opp in db.scalars(select(Opportunity).where(Opportunity.expired_at.is_not(None)))]
    if expired_ids:
        for app in db.scalars(
            select(Application).where(
                Application.opportunity_id.in_(expired_ids),
                Application.status.in_(["discovered", "analyzing", "matched", "pending_approval", "approved", "preparing", "ready_to_submit"]),
            )
        ):
            app.status = "expired"
    db.commit()
    return expired_count


def run_all_sources(db: Session, query: DiscoveryQuery | None = None) -> list[SourceExecutionHistory]:
    return [run_source(db, source, query) for source in db.scalars(select(JobSource).where(JobSource.is_active.is_(True)))]
