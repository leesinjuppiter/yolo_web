"""Allow imported and uploaded images to start without a split."""

from alembic import op
import sqlalchemy as sa

revision = "0002_nullable_splits"
down_revision = "0001_datasets"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("dataset_images", "split", existing_type=sa.String(5), nullable=True)


def downgrade():
    op.alter_column("dataset_images", "split", existing_type=sa.String(5), nullable=False)
