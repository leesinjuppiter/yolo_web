"""Persist image inspection and fingerprint results."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0004_image_analysis"
down_revision = "0003_dataset_analysis"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "dataset_image_analysis",
        sa.Column("image_id", UUID(as_uuid=False), sa.ForeignKey("dataset_images.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("file_signature", JSONB),
        sa.Column("rule_version", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String(64)),
        sa.Column("dhash", sa.String(16)),
        sa.Column("width", sa.Integer),
        sa.Column("height", sa.Integer),
        sa.Column("error", sa.Text),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("dataset_image_analysis")
