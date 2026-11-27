"""Add performance indexes for opportunity, application, approval, and attempt queries."""

from alembic import op

revision = "0009_performance_indexes"
down_revision = "0008_autonomous_operation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_opportunities_source_expired", "opportunities", ["source_id", "expired_at"])
    op.create_index("ix_applications_user_submitted", "applications", ["user_id", "submitted_at"])
    op.create_index("ix_approval_requests_app_status", "approval_requests", ["application_id", "status"])
    op.create_index("ix_application_attempts_app", "application_attempts", ["application_id", "attempt_number"])


def downgrade() -> None:
    op.drop_index("ix_application_attempts_app", table_name="application_attempts")
    op.drop_index("ix_approval_requests_app_status", table_name="approval_requests")
    op.drop_index("ix_applications_user_submitted", table_name="applications")
    op.drop_index("ix_opportunities_source_expired", table_name="opportunities")
