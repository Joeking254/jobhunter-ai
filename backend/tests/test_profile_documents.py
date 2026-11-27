from io import BytesIO

from docx import Document as DocxDocument
from reportlab.pdfgen import canvas


def register(client, email):
    response = client.post("/api/auth/register", json={"email": email, "password": "StrongPassword1", "first_name": "Ada", "last_name": "Lovelace"})
    assert response.status_code == 201
    return response.cookies["jobhunter_csrf"]


def make_docx() -> bytes:
    stream = BytesIO()
    document = DocxDocument()
    document.add_paragraph("Ada Lovelace\nPython and machine learning")
    document.save(stream)
    return stream.getvalue()


def make_pdf() -> bytes:
    stream = BytesIO()
    pdf = canvas.Canvas(stream)
    pdf.drawString(72, 720, "Ada Lovelace CV")
    pdf.save()
    return stream.getvalue()


def test_profile_editing_and_verified_facts(client):
    csrf = register(client, "profile@example.com")
    headers = {"X-CSRF-Token": csrf}
    response = client.put("/api/profile", headers=headers, json={"phone": "+254700000000", "country": "Kenya", "city": "Nairobi", "professional_summary": "Confirmed summary", "portfolio_links": ["https://example.com/portfolio"], "linkedin_url": "https://linkedin.com/in/ada"})
    assert response.status_code == 200
    assert response.json()["personal"]["city"] == "Nairobi"
    assert client.post("/api/profile/education", headers=headers, json={"institution": "University", "qualification": "BSc", "field_of_study": "Computer Science", "current_status": "completed"}).status_code == 201
    assert client.post("/api/profile/experience", headers=headers, json={"company": "Example", "title": "Engineer", "employment_type": "full_time", "achievements": "Built systems"}).status_code == 201
    assert client.post("/api/profile/skills", headers=headers, json={"name": "Python", "category": "programming", "proficiency": "advanced", "years_experience": 5}).status_code == 201
    profile = client.get("/api/profile").json()
    assert profile["completeness_score"] >= 75
    facts = client.get("/api/profile/facts").json()
    assert any(fact["field_key"] == "professional_summary" and fact["status"] == "confirmed" and fact["source"] == "user" for fact in facts)


def test_pdf_docx_upload_parse_default_preview_and_private_download(client):
    csrf = register(client, "documents@example.com")
    headers = {"X-CSRF-Token": csrf}
    pdf_response = client.post("/api/documents", headers=headers, data={"category": "cv", "is_default": "true"}, files={"file": ("cv.pdf", make_pdf(), "application/pdf")})
    assert pdf_response.status_code == 201
    pdf_id = pdf_response.json()["id"]
    assert pdf_response.json()["is_default"] is True
    assert "Ada Lovelace CV" in client.get(f"/api/documents/{pdf_id}/preview").text
    assert client.get(f"/api/documents/{pdf_id}/download").status_code == 200

    docx_response = client.post("/api/documents", headers=headers, data={"category": "cv"}, files={"file": ("cv.docx", make_docx(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert docx_response.status_code == 201
    assert "Python and machine learning" in client.get(f"/api/documents/{docx_response.json()['id']}/preview").text
    facts = client.get("/api/profile/facts").json()
    assert any(fact["status"] == "suggested" and fact["source"] == "document_extraction" for fact in facts)
    assert client.post(f"/api/documents/{docx_response.json()['id']}/default", headers=headers).status_code == 200
    assert sum(item["is_default"] for item in client.get("/api/documents").json()) == 1


def test_documents_are_private_to_the_owner(client):
    csrf = register(client, "owner@example.com")
    response = client.post("/api/documents", headers={"X-CSRF-Token": csrf}, data={"category": "other"}, files={"file": ("support.pdf", make_pdf(), "application/pdf")})
    document_id = response.json()["id"]
    client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
    register(client, "other@example.com")
    assert client.get(f"/api/documents/{document_id}/download").status_code == 404
