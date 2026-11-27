import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_csrf
from app.models.models import SavedSearch, User

router = APIRouter(prefix="/saved-searches", tags=["search-config"])


class SavedSearchInput(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    query: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class SavedSearchUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    query: str | None = None
    filters: dict[str, Any] | None = None
    is_active: bool | None = None


def _serialize(row: SavedSearch) -> dict[str, Any]:
    try:
        filters = json.loads(row.filters or "{}")
    except json.JSONDecodeError:
        filters = {}
    return {
        "id": row.id,
        "name": row.name,
        "query": row.query,
        "filters": filters,
        "is_active": row.is_active,
        "created_at": row.created_at,
    }


@router.get("")
def list_saved_searches(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return [_serialize(row) for row in db.scalars(select(SavedSearch).where(SavedSearch.user_id == user.id).order_by(SavedSearch.created_at.desc()))]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_saved_search(
    payload: SavedSearchInput,
    user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    existing = db.scalar(select(SavedSearch).where(SavedSearch.user_id == user.id, SavedSearch.name == payload.name.strip()))
    if existing is not None:
        raise HTTPException(status_code=409, detail="A saved search with this name already exists")
    row = SavedSearch(
        user_id=user.id,
        name=payload.name.strip(),
        query=payload.query,
        filters=json.dumps(payload.filters),
        is_active=payload.is_active,
    )
    db.add(row)
    db.commit()
    return _serialize(row)


@router.put("/{search_id}")
def update_saved_search(
    search_id: str,
    payload: SavedSearchUpdate,
    user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    row = db.scalar(select(SavedSearch).where(SavedSearch.id == search_id, SavedSearch.user_id == user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Saved search not found")
    data = payload.model_dump(exclude_unset=True)
    if "filters" in data and data["filters"] is not None:
        data["filters"] = json.dumps(data["filters"])
    for field, value in data.items():
        setattr(row, field, value)
    db.commit()
    return _serialize(row)


@router.delete("/{search_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_saved_search(
    search_id: str,
    user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> None:
    row = db.scalar(select(SavedSearch).where(SavedSearch.id == search_id, SavedSearch.user_id == user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Saved search not found")
    db.delete(row)
    db.commit()
