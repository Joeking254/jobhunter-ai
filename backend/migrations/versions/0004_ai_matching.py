"""Add AI analysis, match details, and career preference fields."""

from alembic import op
import sqlalchemy as sa

revision = "0004_ai_matching"
down_revision = "0003_discovery_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, column_type, kwargs in [
        ("work_authorization", sa.String(120), {"nullable": True}),
        ("preferred_locations", sa.Text(), {"nullable": True}),
        ("remote_only", sa.Boolean(), {"nullable": False, "server_default": "0"}),
        ("opportunity_types", sa.Text(), {"nullable": True}),
        ("career_preferences", sa.Text(), {"nullable": True}),
    ]:
        op.add_column("user_settings", sa.Column(name, column_type, **kwargs))
    with op.batch_alter_table("job_matches") as batch_op:
        for name, column_type, kwargs in [
            ("eligible", sa.Boolean(), {"nullable": False, "server_default": "1"}),
            ("risk_level", sa.String(30), {"nullable": True}),
            ("analysis_json", sa.Text(), {"nullable": True}),
            ("recommended_cv_id", sa.String(36), {"nullable": True}),
            ("next_action", sa.String(120), {"nullable": True}),
        ]:
            batch_op.add_column(sa.Column(name, column_type, **kwargs))
        batch_op.create_foreign_key("fk_job_matches_recommended_cv", "documents", ["recommended_cv_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_job_matches_user_eligible", "job_matches", ["user_id", "eligible"])


def downgrade() -> None:
    op.drop_index("ix_job_matches_user_eligible", table_name="job_matches")
    with op.batch_alter_table("job_matches") as batch_op:
        batch_op.drop_constraint("fk_job_matches_recommended_cv", type_="foreignkey")
        for name in ["next_action", "recommended_cv_id", "analysis_json", "risk_level", "eligible"]:
            batch_op.drop_column(name)
    for name in ["career_preferences", "opportunity_types", "remote_only", "preferred_locations", "work_authorization"]:
        op.drop_column("user_settings", name)
