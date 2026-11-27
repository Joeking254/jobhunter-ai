import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_admin, require_csrf
from app.models.models import JobSource, User
from app.services.discovery.connectors import CONNECTOR_TYPES, FUTURE_CONNECTORS
from app.services.discovery.runner import run_source

router = APIRouter(prefix="/sources", tags=["discovery"])


class SourceInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1, max_length=512)
    connector_type: str
    config: dict = {}


@router.get("")
def list_sources(_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = []
    for source in db.scalars(select(JobSource).order_by(JobSource.name)):
        try:
            config = json.loads(source.config_json or "{}")
        except json.JSONDecodeError:
            config = {}
        rows.append(
            {
                "id": source.id,
                "name": source.name,
                "base_url": source.base_url,
                "connector_type": source.connector_type,
                "is_active": source.is_active,
                "reliability_score": source.reliability_score,
                "last_success_at": source.last_success_at,
                "automation_permitted": bool(config.get("automation_permitted", False)),
            }
        )
    return rows


@router.post("")
def create_source(payload: SourceInput, _admin: User = Depends(require_admin), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> dict[str, str]:
    if payload.connector_type not in CONNECTOR_TYPES:
        raise HTTPException(status_code=422, detail=f"Unsupported connector; future connectors reserved: {sorted(FUTURE_CONNECTORS)}")
    source = JobSource(name=payload.name, base_url=payload.base_url, connector_type=payload.connector_type, config_json=json.dumps(payload.config))
    db.add(source)
    db.commit()
    return {"id": source.id}


@router.post("/{source_id}/toggle")
def toggle_source(source_id: str, _admin: User = Depends(require_admin), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> dict[str, bool]:
    source = db.get(JobSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    source.is_active = not source.is_active
    db.commit()
    return {"is_active": source.is_active}


@router.post("/{source_id}/run")
def run_single_source(source_id: str, _admin: User = Depends(require_admin), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    source = db.get(JobSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    history = run_source(db, source)
    return {
        "status": history.status,
        "fetched_count": history.fetched_count,
        "created_count": history.created_count,
        "updated_count": history.updated_count,
        "error_message": history.error_message,
    }
