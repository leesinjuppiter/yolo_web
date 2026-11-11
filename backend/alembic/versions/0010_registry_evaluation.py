"""Registry metadata and immutable evaluation run records."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0010_registry_evaluation"
down_revision = "0009_training_sources"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("model_versions", sa.Column("display_name", sa.String(120)))
    op.add_column("model_versions", sa.Column("description", sa.String(2000), nullable=False, server_default=""))
    op.add_column("model_versions", sa.Column("lifecycle", sa.String(12), nullable=False, server_default="candidate"))
    op.create_table("evaluation_runs",
        sa.Column("id", pg.UUID(as_uuid=False), primary_key=True),
        sa.Column("version_id", pg.UUID(as_uuid=False), sa.ForeignKey("model_versions.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(120), unique=True),
        sa.Column("config", pg.JSONB(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("phase", sa.String(32), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("report", pg.JSONB()), sa.Column("error", sa.String(2000)),
        sa.Column("logs", pg.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("finished_at", sa.DateTime(timezone=True)))
    op.create_index("ix_evaluation_status_created", "evaluation_runs", ["status", "created_at"])
    op.create_index("ix_evaluation_version_created", "evaluation_runs", ["version_id", "created_at"])


def downgrade():
    op.drop_table("evaluation_runs")
    for column in ("lifecycle", "description", "display_name"):
        op.drop_column("model_versions", column)
