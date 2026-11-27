import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_csrf
from app.core.config import settings
from app.models.models import Document, GeneratedDocument, Opportunity, User
from app.services.generation.service import _write_file, generate_documents, unsupported_claims, verified_context

router = APIRouter(prefix="/generation", tags=["document-generation"])


class GenerateRequest(BaseModel):
    formats: list[str] = Field(default_factory=lambda: ["docx", "pdf"])
    questions: list[str] = Field(default_factory=list)


class EditRequest(BaseModel):
    text: str = Field(min_length=1)


def _owned(generated_id: str, user: User, db: Session) -> GeneratedDocument:
    generated = db.scalar(select(GeneratedDocument).where(GeneratedDocument.id == generated_id, GeneratedDocument.user_id == user.id))
    if generated is None:
        raise HTTPException(status_code=404, detail="Generated document not found")
    return generated


@router.post("/opportunities/{opportunity_id}")
def generate_for_opportunity(opportunity_id: str, payload: GenerateRequest, user: User = Depends(get_current_user), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> list[dict]:
    opportunity = db.get(Opportunity, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    try:
        documents = generate_documents(db, user, opportunity, payload.questions, payload.formats)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return [{"id": item.id, "document_type": item.document_type, "format": item.file_format, "version": item.version, "template": item.template_name} for item in documents]


@router.get("/opportunities/{opportunity_id}")
def list_generated_for_opportunity(opportunity_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [{"id": item.id, "document_type": item.document_type, "format": item.file_format, "version": item.version, "template": item.template_name, "status": item.generation_status} for item in db.scalars(select(GeneratedDocument).where(GeneratedDocument.opportunity_id == opportunity_id, GeneratedDocument.user_id == user.id).order_by(GeneratedDocument.created_at.desc()))]


@router.get("/{generated_id}/preview", response_class=PlainTextResponse)
def preview_generated(generated_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> str:
    return _owned(generated_id, user, db).editable_text


@router.get("/{generated_id}/download")
def download_generated(generated_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    generated = _owned(generated_id, user, db)
    document = db.get(Document, generated.document_id)
    path = Path(settings.document_storage_dir).resolve() / user.id / document.storage_key if document else Path("__missing__")
    if document is None or path.parent != Path(settings.document_storage_dir).resolve() / user.id or not path.is_file():
        raise HTTPException(status_code=404, detail="Generated file not found")
    return FileResponse(path, media_type=document.mime_type, filename=document.name, content_disposition_type="attachment")


@router.put("/{generated_id}")
def edit_generated(generated_id: str, payload: EditRequest, user: User = Depends(get_current_user), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> dict[str, str]:
    generated = _owned(generated_id, user, db)
    opportunity = db.get(Opportunity, generated.opportunity_id)
    context = verified_context(db, user, opportunity, [])
    if unsupported_claims(payload.text, context):
        raise HTTPException(status_code=422, detail="Edited document contains unsupported claims")
    document = db.get(Document, generated.document_id)
    path = Path(settings.document_storage_dir).resolve() / user.id / document.storage_key
    _write_file(payload.text, generated.file_format, path)
    generated.editable_text = payload.text
    document.extracted_text = payload.text
    document.content_hash = hashlib.sha256(payload.text.encode()).hexdigest()
    document.size_bytes = path.stat().st_size
    db.commit()
    return {"status": "updated", "id": generated.id}


@router.post("/{generated_id}/regenerate")
def regenerate_generated(generated_id: str, payload: GenerateRequest, user: User = Depends(get_current_user), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> list[dict]:
    generated = _owned(generated_id, user, db)
    opportunity = db.get(Opportunity, generated.opportunity_id)
    try:
        documents = generate_documents(db, user, opportunity, payload.questions, [generated.file_format])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return [{"id": item.id, "document_type": item.document_type, "format": item.file_format, "version": item.version} for item in documents]
