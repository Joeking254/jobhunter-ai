from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.models import User
from app.services.monitoring import collect_monitoring_summary

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/summary")
def monitoring_summary(
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return collect_monitoring_summary(db)
