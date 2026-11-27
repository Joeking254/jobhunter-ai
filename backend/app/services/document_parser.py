"""Deterministic text extraction for user-provided PDF and DOCX files."""

from io import BytesIO

from docx import Document as DocxDocument
from pypdf import PdfReader


def extract_text(content: bytes, mime_type: str, filename: str) -> str:
    extension = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if mime_type == "application/pdf" or extension == "pdf":
        return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages).strip()
    if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" or extension == "docx":
        document = DocxDocument(BytesIO(content))
        return "\n".join(paragraph.text for paragraph in document.paragraphs).strip()
    return ""
