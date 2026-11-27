import hashlib
import mimetypes
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_csrf
from app.core.config import settings
from app.models.models import Document, ProfileFact, User
from app.services.document_parser import extract_text

router = APIRouter(prefix="/documents", tags=["documents"])
ALLOWED = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}
ALLOWED_CATEGORIES = {"cv", "certificate", "academic", "portfolio", "other"}


def _storage_root(user_id: str) -> Path:
    root = Path(settings.document_storage_dir).resolve() / user_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def _document_path(document: Document) -> Path:
    path = Path(settings.document_storage_dir).resolve() / document.user_id / document.storage_key
    if path.parent != (Path(settings.document_storage_dir).resolve() / document.user_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return path


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    category: str = Form("other"),
    is_default: bool = Form(False),
    replaces_document_id: str | None = Form(None),
    user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict:
    if category not in ALLOWED_CATEGORIES:
        raise HTTPException(status_code=422, detail="Unsupported document category")
    suffix = Path(file.filename or "").suffix.lower()
    mime_type = file.content_type or mimetypes.types_map.get(suffix, "")
    if mime_type not in ALLOWED or suffix != ALLOWED[mime_type]:
        raise HTTPException(status_code=415, detail="Only PDF and DOCX documents are supported")
    max_bytes = settings.max_document_size_mb * 1024 * 1024
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail="Document exceeds the size limit")
    if mime_type == "application/pdf" and not content.startswith(b"%PDF"):
        raise HTTPException(status_code=415, detail="Invalid PDF file")
    if mime_type.endswith("wordprocessingml.document") and not content.startswith(b"PK"):
        raise HTTPException(status_code=415, detail="Invalid DOCX file")
    document_id = secrets.token_hex(16)
    storage_key = f"{document_id}{suffix}"
    path = _storage_root(user.id) / storage_key
    path.write_bytes(content)
    extracted = extract_text(content, mime_type, file.filename or storage_key)
    if is_default and category == "cv":
        db.execute(update(Document).where(Document.user_id == user.id, Document.document_type == "cv").values(is_default=False))
    document = Document(id=document_id, user_id=user.id, name=file.filename or storage_key, document_type=category, storage_key=storage_key, content_hash=hashlib.sha256(content).hexdigest(), mime_type=mime_type, size_bytes=len(content), extracted_text=extracted, is_default=is_default, replaced_document_id=replaces_document_id)
    db.add(document)
    if extracted:
        db.add(ProfileFact(user_id=user.id, field_key="document_extracted_text", value=extracted, status="suggested", source="document_extraction", evidence_document_id=document.id))
    db.commit()
    return {"id": document.id, "name": document.name, "category": document.document_type, "size_bytes": document.size_bytes, "has_extracted_text": bool(extracted), "is_default": document.is_default}


@router.get("")
def list_documents(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [{"id": item.id, "name": item.name, "category": item.document_type, "mime_type": item.mime_type, "size_bytes": item.size_bytes, "is_default": item.is_default, "created_at": item.created_at} for item in db.scalars(select(Document).where(Document.user_id == user.id).order_by(Document.created_at.desc()))]


@router.get("/{document_id}/download")
def download_document(document_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    document = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == user.id))
    if document is None or not _document_path(document).is_file():
        raise HTTPException(status_code=404, detail="Document not found")
    return FileResponse(_document_path(document), media_type=document.mime_type, filename=document.name, content_disposition_type="attachment")


@router.get("/{document_id}/preview", response_class=PlainTextResponse)
def preview_document(document_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> str:
    document = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == user.id))
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document.extracted_text or "No text could be extracted from this document."


@router.post("/{document_id}/default")
def set_default_cv(document_id: str, user: User = Depends(get_current_user), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> dict[str, str]:
    document = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == user.id, Document.document_type == "cv"))
    if document is None:
        raise HTTPException(status_code=404, detail="CV not found")
    db.execute(update(Document).where(Document.user_id == user.id, Document.document_type == "cv").values(is_default=False))
    document.is_default = True
    db.commit()
    return {"status": "default_cv_updated"}


@router.delete("/{document_id}")
def delete_document(document_id: str, user: User = Depends(get_current_user), _csrf=Depends(require_csrf), db: Session = Depends(get_db)) -> dict[str, str]:
    document = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == user.id))
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    path = _document_path(document)
    if path.is_file():
        path.unlink()
    db.delete(document)
    db.commit()
    return {"status": "deleted"}
