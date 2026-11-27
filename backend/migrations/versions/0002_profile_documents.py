"""Add career profile fields, document metadata, and verified profile facts."""

from alembic import op
import sqlalchemy as sa

revision = "0002_profile_documents"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    profile_columns = [
        ("phone", sa.String(40)),
        ("country", sa.String(120)),
        ("city", sa.String(120)),
        ("professional_summary", sa.Text()),
        ("portfolio_links", sa.Text()),
        ("linkedin_url", sa.String(512)),
    ]
    for name, column_type in profile_columns:
        op.add_column("career_profiles", sa.Column(name, column_type, nullable=True))
    for name, column_type in [("qualification", sa.String(255)), ("current_status", sa.String(50))]:
        op.add_column("education", sa.Column(name, column_type, nullable=True))
    for name, column_type in [("employment_type", sa.String(50)), ("achievements", sa.Text())]:
        op.add_column("experience", sa.Column(name, column_type, nullable=True))
    for name, column_type, kwargs in [
        ("category", sa.String(80), {"nullable": False, "server_default": "technical"}),
        ("years_experience", sa.Integer(), {"nullable": True}),
    ]:
        op.add_column("skills", sa.Column(name, column_type, **kwargs))
    with op.batch_alter_table("documents") as batch_op:
        for name, column_type, kwargs in [
            ("mime_type", sa.String(120), {"nullable": True}),
            ("size_bytes", sa.Integer(), {"nullable": True}),
            ("extracted_text", sa.Text(), {"nullable": True}),
            ("is_default", sa.Boolean(), {"nullable": False, "server_default": "0"}),
            ("replaced_document_id", sa.String(36), {"nullable": True}),
        ]:
            batch_op.add_column(sa.Column(name, column_type, **kwargs))
        batch_op.create_foreign_key("fk_documents_replaced_document", "documents", ["replaced_document_id"], ["id"], ondelete="SET NULL")
    op.create_table(
        "profile_facts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_key", sa.String(120), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="confirmed"),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("evidence_document_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="SET NULL")),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_profile_facts_user_field_status", "profile_facts", ["user_id", "field_key", "status"])


def downgrade() -> None:
    op.drop_index("ix_profile_facts_user_field_status", table_name="profile_facts")
    op.drop_table("profile_facts")
    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_constraint("fk_documents_replaced_document", type_="foreignkey")
        for name in ["replaced_document_id", "is_default", "extracted_text", "size_bytes", "mime_type"]:
            batch_op.drop_column(name)
    for name in ["years_experience", "category"]:
        op.drop_column("skills", name)
    for name in ["achievements", "employment_type"]:
        op.drop_column("experience", name)
    for name in ["current_status", "qualification"]:
        op.drop_column("education", name)
    for name in ["linkedin_url", "portfolio_links", "professional_summary", "city", "country", "phone"]:
        op.drop_column("career_profiles", name)
