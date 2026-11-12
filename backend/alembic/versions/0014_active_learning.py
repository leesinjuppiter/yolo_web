"""Human-reviewed active-learning iterations and immutable training inputs."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0014_active_learning"
down_revision = "0013_training_environment_null"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("active_learning_iterations", _id(),
        sa.Column("name", sa.String(120), nullable=False), sa.Column("goal", sa.String(2000), nullable=False),
        _fk("dataset_id", "datasets"), _fk("baseline_version_id", "model_versions"),
        _fk("source_task_id", "training_tasks"), sa.Column("task_type", sa.String(12), nullable=False),
        sa.Column("source", pg.JSONB(), nullable=False), sa.Column("result", pg.JSONB(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)), _created())
    op.create_table("active_learning_tasks", _id(), _fk("iteration_id", "active_learning_iterations"),
        sa.Column("idempotency_key", sa.String(120), unique=True),
        sa.Column("config", pg.JSONB(), nullable=False), sa.Column("inputs", pg.JSONB(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False), sa.Column("phase", sa.String(32), nullable=False),
        sa.Column("processed", sa.Integer(), nullable=False), sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False), sa.Column("logs", pg.JSONB(), nullable=False),
        sa.Column("error", sa.String(1000)), _created(), sa.Column("finished_at", sa.DateTime(timezone=True)))
    op.create_index("ix_active_learning_tasks_iteration_id", "active_learning_tasks", ["iteration_id"])
    op.create_index("ix_active_learning_tasks_status", "active_learning_tasks", ["status"])
    op.create_table("active_learning_candidates", _id(), _fk("iteration_id", "active_learning_iterations"),
        _fk("task_id", "active_learning_tasks", nullable=True), sa.Column("image_id", pg.UUID(), nullable=False),
        sa.Column("purpose", sa.String(12), nullable=False), sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("data", pg.JSONB(), nullable=False), sa.Column("review", pg.JSONB()), _created(),
        sa.UniqueConstraint("iteration_id", "image_id", "purpose", name="uq_al_candidate_image"))
    op.create_index("ix_active_learning_candidates_iteration_id", "active_learning_candidates", ["iteration_id"])
    op.create_index("ix_active_learning_candidates_task_id", "active_learning_candidates", ["task_id"])
    op.create_table("active_learning_manifests", _id(), _fk("iteration_id", "active_learning_iterations"),
        sa.Column("digest", sa.String(64), nullable=False), sa.Column("payload", pg.JSONB(), nullable=False), _created())
    op.create_index("ix_active_learning_manifests_iteration_id", "active_learning_manifests", ["iteration_id"])
    for table in ("iterations", "tasks", "candidates", "manifests"):
        topic = "iterations" if table == "iterations" else "active_learning"
        op.execute(f"CREATE TRIGGER workbench_change AFTER INSERT OR UPDATE OR DELETE ON active_learning_{table} "
                   f"FOR EACH ROW EXECUTE FUNCTION workbench_notify_change('{topic}')")


def downgrade():
    for table in ("manifests", "candidates", "tasks", "iterations"):
        op.drop_table("active_learning_" + table)


def _id():
    return sa.Column("id", pg.UUID(), primary_key=True)


def _fk(name, target, nullable=False):
    return sa.Column(name, pg.UUID(), sa.ForeignKey(target + ".id"), nullable=nullable)


def _created():
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
