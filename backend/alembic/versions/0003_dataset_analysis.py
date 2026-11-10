"""Store durable dataset analysis jobs and the latest report snapshots."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_dataset_analysis"
down_revision = "0002_nullable_splits"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "dataset_analysis_jobs",
        sa.Column("dataset_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("kind", sa.String(12), primary_key=True),
        sa.Column("revision", sa.BigInteger, nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("claim_token", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed", sa.Integer, nullable=True),
        sa.Column("total", sa.Integer, nullable=True),
        sa.Column("error", sa.String(200), nullable=True),
        sa.CheckConstraint("kind IN ('validate','duplicates','quality')", name="ck_dataset_analysis_jobs_kind"),
        sa.CheckConstraint("status IN ('queued','running','ready','failed')", name="ck_dataset_analysis_jobs_status"),
    )
    op.create_index("ix_dataset_analysis_jobs_schedule", "dataset_analysis_jobs", ["status", "available_at"])
    op.create_table(
        "dataset_report_snapshots",
        sa.Column("dataset_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("kind", sa.String(12), primary_key=True),
        sa.Column("revision", sa.BigInteger, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.CheckConstraint("kind IN ('validate','duplicates','quality')", name="ck_dataset_report_snapshots_kind"),
    )
    op.execute("""
        INSERT INTO dataset_analysis_jobs (dataset_id, kind, revision, status, priority, available_at, attempts)
        SELECT datasets.id, kinds.kind, 1, 'queued', 0, now() + interval '2 seconds', 0
        FROM datasets
        CROSS JOIN (VALUES ('validate'), ('duplicates'), ('quality')) AS kinds(kind)
        WHERE EXISTS (SELECT 1 FROM dataset_images WHERE dataset_images.dataset_id = datasets.id)
    """)


def downgrade():
    op.drop_table("dataset_report_snapshots")
    op.drop_table("dataset_analysis_jobs")
