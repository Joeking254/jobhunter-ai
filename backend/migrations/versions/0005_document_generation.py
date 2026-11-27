"""Add generated application document versions and history."""

from alembic import op
import sqlalchemy as sa

revision = "0005_document_generation"
down_revision = "0004_ai_matching"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generated_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("opportunity_id", sa.String(36), sa.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_type", sa.String(40), nullable=False),
        sa.Column("file_format", sa.String(10), nullable=False),
        sa.Column("template_name", sa.String(80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("editable_text", sa.Text(), nullable=False),
        sa.Column("prompt_hash", sa.String(128)),
        sa.Column("claims_json", sa.Text()),
        sa.Column("generation_status", sa.String(30), nullable=False, server_default="ready"),
        sa.UniqueConstraint("document_id", name="uq_generated_document_document"),
    )
    op.create_index("ix_generated_documents_user_opportunity", "generated_documents", ["user_id", "opportunity_id"])


def downgrade() -> None:
    op.drop_index("ix_generated_documents_user_opportunity", table_name="generated_documents")
    op.drop_table("generated_documents")
