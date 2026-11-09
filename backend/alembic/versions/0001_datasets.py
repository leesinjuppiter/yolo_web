"""Create datasets, classes and annotated images."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001_datasets"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "datasets",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("task_type", sa.String(12), nullable=False),
        sa.Column("keypoint_names", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("task_type IN ('detect','segment','obb','pose','classify')", name="ck_datasets_task"),
    )
    op.create_table(
        "dataset_classes",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("dataset_id", UUID(as_uuid=False), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("color", sa.String(7), nullable=False),
        sa.Column("index", sa.Integer, nullable=False),
        sa.UniqueConstraint("dataset_id", "name", name="uq_dataset_classes_name"),
        sa.UniqueConstraint("dataset_id", "index", name="uq_dataset_classes_index"),
        sa.CheckConstraint('"index" >= 0', name="ck_dataset_classes_index"),
    )
    op.create_table(
        "dataset_images",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("dataset_id", UUID(as_uuid=False), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("width", sa.Integer, nullable=False),
        sa.Column("height", sa.Integer, nullable=False),
        sa.Column("split", sa.String(5), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("storage_path", sa.String(160), unique=True, nullable=False),
        sa.Column("annotations", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("split IN ('train','val','test')", name="ck_dataset_images_split"),
        sa.CheckConstraint("status IN ('unlabeled','negative','annotated')", name="ck_dataset_images_status"),
        sa.CheckConstraint("width > 0 AND height > 0", name="ck_dataset_images_size"),
        sa.CheckConstraint("version >= 0", name="ck_dataset_images_version"),
    )
    op.create_index("ix_dataset_images_dataset_id", "dataset_images", ["dataset_id"])


def downgrade():
    op.drop_table("dataset_images")
    op.drop_table("dataset_classes")
    op.drop_table("datasets")
