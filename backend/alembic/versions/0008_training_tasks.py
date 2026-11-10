"""Persist CPU training jobs, observations, and registered model versions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0008_training_tasks"
down_revision = "0007_exact_duplicate_review"
branch_labels = None
depends_on = None


def _observations():
    op.create_table(
        "training_logs",
        sa.Column("task_id", pg.UUID(), sa.ForeignKey("training_tasks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("sequence", sa.BigInteger(), primary_key=True),
        sa.Column("time", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("level", sa.String(8), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
    )
    op.create_table(
        "training_metrics",
        sa.Column("task_id", pg.UUID(), sa.ForeignKey("training_tasks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("sequence", sa.BigInteger(), primary_key=True),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("values", pg.JSONB(), nullable=False),
        sa.Column("step", sa.Integer()),
        sa.Column("elapsed_seconds", sa.Float()),
    )


def upgrade():
    op.create_table(
        "training_tasks",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("idempotency_key", sa.String(120), unique=True),
        sa.Column("dataset_id", pg.UUID(), nullable=False),
        sa.Column("dataset_name", sa.String(120), nullable=False),
        sa.Column("dataset_image_count", sa.Integer(), nullable=False),
        sa.Column("dataset_class_count", sa.Integer(), nullable=False),
        sa.Column("dataset_revision", sa.String(128)),
        sa.Column("config", pg.JSONB(), nullable=False),
        sa.Column("model_name", sa.String(120), nullable=False),
        sa.Column("architecture", sa.String(32), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("phase", sa.String(40), nullable=False),
        sa.Column("worker_token", sa.String(36)),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("snapshot", pg.JSONB()),
        sa.Column("environment", pg.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("metrics", pg.JSONB(), nullable=False),
        sa.Column("failure", pg.JSONB()),
        sa.Column("artifacts", pg.JSONB(), nullable=False),
        sa.Column("previews", pg.JSONB(), nullable=False),
        sa.CheckConstraint("status IN ('created','queued','running','succeeded','failed','canceled')",
                           name="ck_training_task_status"),
    )
    op.create_index("ix_training_tasks_status_created", "training_tasks", ["status", "created_at"])
    _observations()
    op.create_table(
        "model_versions",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("number", sa.BigInteger(), sa.Identity(), unique=True, nullable=False),
        sa.Column("task_id", pg.UUID(), sa.ForeignKey("training_tasks.id"), unique=True, nullable=False),
        sa.Column("artifact_id", sa.String(80), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table("model_versions")
    op.drop_table("training_metrics")
    op.drop_table("training_logs")
    op.drop_index("ix_training_tasks_status_created", table_name="training_tasks")
    op.drop_table("training_tasks")
