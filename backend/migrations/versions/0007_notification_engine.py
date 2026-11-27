"""Add notification settings fields and notification delivery log table."""

from alembic import op
import sqlalchemy as sa

revision = "0007_notification_engine"
down_revision = "0006_application_submission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, column_type, kwargs in [
        ("telegram_chat_id", sa.String(120), {"nullable": True}),
        ("telegram_enabled", sa.Boolean(), {"nullable": False, "server_default": "0"}),
        ("email_notifications_enabled", sa.Boolean(), {"nullable": False, "server_default": "1"}),
        ("notification_frequency", sa.String(20), {"nullable": False, "server_default": "immediate"}),
        ("min_notification_match_score", sa.Integer(), {"nullable": False, "server_default": "65"}),
    ]:
        op.add_column("user_settings", sa.Column(name, column_type, **kwargs))

    op.create_table(
        "notification_delivery_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("notification_id", sa.String(36), sa.ForeignKey("notifications.id", ondelete="SET NULL"), nullable=True),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("dedupe_key", sa.String(255), nullable=True),
        sa.Column("content_hash", sa.String(128), nullable=True),
        sa.Column("recipient", sa.String(320), nullable=True),
        sa.Column("subject", sa.String(255), nullable=True),
        sa.Column("payload_preview", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("provider_message_id", sa.String(255), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_notif_delivery_user_dedupe", "notification_delivery_logs", ["user_id", "event_type", "dedupe_key"])
    op.create_index("ix_notif_delivery_status_retry", "notification_delivery_logs", ["status", "next_retry_at"])


def downgrade() -> None:
    op.drop_index("ix_notif_delivery_status_retry", table_name="notification_delivery_logs")
    op.drop_index("ix_notif_delivery_user_dedupe", table_name="notification_delivery_logs")
    op.drop_table("notification_delivery_logs")
    for name in [
        "min_notification_match_score",
        "notification_frequency",
        "email_notifications_enabled",
        "telegram_enabled",
        "telegram_chat_id",
    ]:
        op.drop_column("user_settings", name)
