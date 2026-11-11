"""Persist ONNX exports and downloadable package builds."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0011_export_packages"
down_revision = "0010_registry_evaluation"
branch_labels = None
depends_on = None


def _common():
    return [sa.Column("id", pg.UUID(), primary_key=True),
            sa.Column("idempotency_key", sa.String(120), unique=True),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("phase", sa.String(40), nullable=False),
            sa.Column("logs", pg.JSONB(), nullable=False),
            sa.Column("error", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("started_at", sa.DateTime(timezone=True)),
            sa.Column("finished_at", sa.DateTime(timezone=True))]


def upgrade():
    op.create_table("model_export_tasks", *_common(),
                    sa.Column("version_id", pg.UUID(), sa.ForeignKey("model_versions.id"), nullable=False),
                    sa.Column("config", pg.JSONB(), nullable=False),
                    sa.Column("report", pg.JSONB()),
                    sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("ix_model_export_tasks_status", "model_export_tasks", ["status"])
    op.create_table("deployment_packages", *_common(),
                    sa.Column("export_id", pg.UUID(), sa.ForeignKey("model_export_tasks.id"), nullable=False),
                    sa.Column("manifest", pg.JSONB()))
    op.create_index("ix_deployment_packages_status", "deployment_packages", ["status"])


def downgrade():
    op.drop_table("deployment_packages")
    op.drop_table("model_export_tasks")
