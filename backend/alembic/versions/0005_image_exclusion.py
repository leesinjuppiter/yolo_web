"""Allow reversible exclusion of dataset images."""

import sqlalchemy as sa
from alembic import op

revision = "0005_image_exclusion"
down_revision = "0004_image_analysis"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("dataset_images", sa.Column("excluded_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("dataset_images", "excluded_at")
