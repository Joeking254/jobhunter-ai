"""Add bot configuration controls and task execution log metadata."""

from alembic import op
import sqlalchemy as sa

revision = "0008_autonomous_operation"
down_revision = "0007_notification_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, column_type, kwargs in [
        ("queue_name", sa.String(60), {"nullable": False, "server_default": "default"}),
        ("task_id", sa.String(120), {"nullable": True}),
        ("attempt", sa.Integer(), {"nullable": False, "server_default": "1"}),
        ("duration_ms", sa.Integer(), {"nullable": True}),
        ("details_json", sa.Text(), {"nullable": True}),
    ]:
        op.add_column("bot_runs", sa.Column(name, column_type, **kwargs))
    op.create_index("ix_bot_runs_name_started", "bot_runs", ["bot_name", "started_at"])

    op.create_table(
        "bot_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("scope_key", sa.String(40), nullable=False, unique=True),
        sa.Column("bot_paused", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("auto_apply_paused", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("search_frequency_minutes", sa.Integer(), nullable=False, server_default="360"),
        sa.Column("match_strong_threshold", sa.Integer(), nullable=False, server_default="85"),
        sa.Column("match_approval_threshold", sa.Integer(), nullable=False, server_default="65"),
        sa.Column("last_discovery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_analytics_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("bot_configs")
    op.drop_index("ix_bot_runs_name_started", table_name="bot_runs")
    for name in ["details_json", "duration_ms", "attempt", "task_id", "queue_name"]:
        op.drop_column("bot_runs", name)
