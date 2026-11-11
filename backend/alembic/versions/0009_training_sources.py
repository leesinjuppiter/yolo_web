"""Keep model and checkpoint lineage for new training executions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0009_training_sources"
down_revision = "0008_training_tasks"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("training_tasks", sa.Column("parent_model_version_id", pg.UUID(), nullable=True))
    op.add_column("training_tasks", sa.Column("resume_from_task_id", pg.UUID(), nullable=True))
    op.add_column("training_tasks", sa.Column("resume_checkpoint", pg.JSONB(), nullable=True))
    op.create_foreign_key("fk_training_parent_model", "training_tasks", "model_versions",
                          ["parent_model_version_id"], ["id"])
    op.create_foreign_key("fk_training_resume_source", "training_tasks", "training_tasks",
                          ["resume_from_task_id"], ["id"])


def downgrade():
    op.drop_constraint("fk_training_resume_source", "training_tasks", type_="foreignkey")
    op.drop_constraint("fk_training_parent_model", "training_tasks", type_="foreignkey")
    op.drop_column("training_tasks", "resume_checkpoint")
    op.drop_column("training_tasks", "resume_from_task_id")
    op.drop_column("training_tasks", "parent_model_version_id")
