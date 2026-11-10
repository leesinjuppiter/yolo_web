"""Persist human decisions about fingerprinted image pairs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0006_similarity_reviews"
down_revision = "0005_image_exclusion"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "dataset_similarity_reviews",
        sa.Column("dataset_id", UUID(as_uuid=False), sa.ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("first_image_id", UUID(as_uuid=False), sa.ForeignKey("dataset_images.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("second_image_id", UUID(as_uuid=False), sa.ForeignKey("dataset_images.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("first_sha256", sa.String(64), primary_key=True),
        sa.Column("second_sha256", sa.String(64), primary_key=True),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("first_image_id < second_image_id", name="ck_dataset_similarity_reviews_pair_order"),
        sa.CheckConstraint("decision IN ('not_similar','keep_both','discard_first','discard_second')",
                           name="ck_dataset_similarity_reviews_decision"),
    )
    op.create_index("ix_dataset_similarity_reviews_first_image_id", "dataset_similarity_reviews", ["first_image_id"])
    op.create_index("ix_dataset_similarity_reviews_second_image_id", "dataset_similarity_reviews", ["second_image_id"])
    op.execute("""
        UPDATE dataset_analysis_jobs
        SET revision = revision + 1, status = 'queued', priority = 0, attempts = 0,
            available_at = now() + interval '2 seconds', claim_token = NULL, lease_until = NULL,
            completed = NULL, total = NULL, error = NULL
        WHERE kind = 'duplicates'
    """)


def downgrade():
    op.drop_table("dataset_similarity_reviews")
