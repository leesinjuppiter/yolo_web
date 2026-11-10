"""Regenerate duplicate snapshots for exact file matching and review."""

from alembic import op

revision = "0007_exact_duplicate_review"
down_revision = "0006_similarity_reviews"
branch_labels = None
depends_on = None


def _requeue_duplicate_reports():
    op.execute("DELETE FROM dataset_report_snapshots WHERE kind = 'duplicates'")
    op.execute("""
        UPDATE dataset_analysis_jobs
        SET revision = revision + 1, status = 'queued', priority = 0, attempts = 0,
            available_at = now(), claim_token = NULL, lease_until = NULL,
            completed = NULL, total = NULL, error = NULL
        WHERE kind = 'duplicates'
    """)


def upgrade():
    _requeue_duplicate_reports()


def downgrade():
    _requeue_duplicate_reports()
