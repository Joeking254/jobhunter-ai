"""Add safe application preparation and submission state fields."""

from alembic import op
import sqlalchemy as sa

revision = "0006_application_submission"
down_revision = "0005_document_generation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, column_type, kwargs in [
        ("application_url", sa.String(1024), {"nullable": True}),
        ("confirmation_reference", sa.String(255), {"nullable": True}),
        ("last_error", sa.Text(), {"nullable": True}),
        ("prepared_at", sa.DateTime(timezone=True), {"nullable": True}),
        ("submitted_at", sa.DateTime(timezone=True), {"nullable": True}),
        ("requires_manual_intervention", sa.Boolean(), {"nullable": False, "server_default": "0"}),
        ("source_permits_automation", sa.Boolean(), {"nullable": False, "server_default": "0"}),
        ("required_documents_verified", sa.Boolean(), {"nullable": False, "server_default": "0"}),
        ("required_answers_verified", sa.Boolean(), {"nullable": False, "server_default": "0"}),
        ("sensitive_declarations_verified", sa.Boolean(), {"nullable": False, "server_default": "0"}),
    ]:
        op.add_column("applications", sa.Column(name, column_type, **kwargs))


def downgrade() -> None:
    for name in ["sensitive_declarations_verified", "required_answers_verified", "required_documents_verified", "source_permits_automation", "requires_manual_intervention", "submitted_at", "prepared_at", "last_error", "confirmation_reference", "application_url"]:
        op.drop_column("applications", name)
