"""Add connector configuration and normalized opportunity discovery fields."""

from alembic import op
import sqlalchemy as sa

revision = "0003_discovery_engine"
down_revision = "0002_profile_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, column_type, kwargs in [
        ("connector_type", sa.String(80), {"nullable": False, "server_default": "rss"}),
        ("config_json", sa.Text(), {"nullable": True}),
        ("reliability_score", sa.Integer(), {"nullable": False, "server_default": "100"}),
        ("last_success_at", sa.DateTime(timezone=True), {"nullable": True}),
    ]:
        op.add_column("job_sources", sa.Column(name, column_type, **kwargs))
    for name, column_type, kwargs in [
        ("deadline", sa.DateTime(timezone=True), {"nullable": True}),
        ("experience_requirements", sa.Text(), {"nullable": True}),
        ("salary_text", sa.String(255), {"nullable": True}),
        ("salary_min", sa.Integer(), {"nullable": True}),
        ("salary_max", sa.Integer(), {"nullable": True}),
        ("salary_currency", sa.String(10), {"nullable": True}),
        ("remote_only", sa.Boolean(), {"nullable": False, "server_default": "0"}),
        ("categories", sa.Text(), {"nullable": True}),
        ("expired_at", sa.DateTime(timezone=True), {"nullable": True}),
        ("last_seen_at", sa.DateTime(timezone=True), {"nullable": True}),
    ]:
        op.add_column("opportunities", sa.Column(name, column_type, **kwargs))
    op.create_index("ix_opportunities_remote_deadline", "opportunities", ["remote_only", "deadline"])
    op.create_table(
        "source_execution_history",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("job_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("pages_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fetched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
    )
    op.create_index("ix_source_history_source_started", "source_execution_history", ["source_id", "started_at"])


def downgrade() -> None:
    op.drop_index("ix_source_history_source_started", table_name="source_execution_history")
    op.drop_table("source_execution_history")
    op.drop_index("ix_opportunities_remote_deadline", table_name="opportunities")
    for name in ["last_seen_at", "expired_at", "categories", "remote_only", "salary_currency", "salary_max", "salary_min", "salary_text", "experience_requirements", "deadline"]:
        op.drop_column("opportunities", name)
    for name in ["last_success_at", "reliability_score", "config_json", "connector_type"]:
        op.drop_column("job_sources", name)
