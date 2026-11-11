"""Publish committed changes for the browser notification stream."""

from alembic import op

revision = "0012_change_notifications"
down_revision = "0011_export_packages"
branch_labels = None
depends_on = None

TABLES = {
    "datasets": "datasets", "dataset_classes": "datasets", "dataset_images": "datasets",
    "dataset_similarity_reviews": "datasets", "dataset_analysis_jobs": "reports",
    "dataset_report_snapshots": "reports", "training_tasks": "training",
    "training_logs": "training", "training_metrics": "training", "model_versions": "models",
    "evaluation_runs": "evaluations", "model_export_tasks": "exports", "deployment_packages": "packages",
}


def upgrade():
    op.execute("""
    CREATE FUNCTION workbench_notify_change() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE item jsonb; previous jsonb; topic text := TG_ARGV[0];
    BEGIN
      IF TG_OP = 'DELETE' THEN item := to_jsonb(OLD); ELSE item := to_jsonb(NEW); END IF;
      IF TG_OP = 'UPDATE' THEN
        previous := to_jsonb(OLD);
        IF TG_TABLE_NAME = 'training_tasks' THEN
          IF (item - 'heartbeat_at' - 'worker_token') = (previous - 'heartbeat_at' - 'worker_token')
            THEN RETURN NULL; END IF;
          IF (item - 'heartbeat_at' - 'worker_token' - 'environment') =
             (previous - 'heartbeat_at' - 'worker_token' - 'environment') AND
             (COALESCE(item->'environment','{}') - 'resourceSample') =
             (COALESCE(previous->'environment','{}') - 'resourceSample')
            THEN topic := 'resources'; END IF;
        ELSIF TG_TABLE_NAME = 'dataset_analysis_jobs' THEN
          IF (item - ARRAY['lease_until','claim_token','available_at','attempts']) =
             (previous - ARRAY['lease_until','claim_token','available_at','attempts'])
            THEN RETURN NULL; END IF;
        ELSIF item = previous THEN RETURN NULL;
        END IF;
      END IF;
      PERFORM pg_notify('workbench_changes', jsonb_strip_nulls(jsonb_build_object(
        'topic', topic, 'table', TG_TABLE_NAME,
        'id', CASE WHEN TG_ARGV[0] IN ('datasets','reports') THEN COALESCE(item->>'dataset_id',item->>'id')
                   WHEN TG_ARGV[0] = 'training' THEN COALESCE(item->>'task_id',item->>'id')
                   ELSE item->>'id' END,
        'kind', item->>'kind'))::text);
      RETURN NULL;
    END $$;
    """)
    for table, topic in TABLES.items():
        op.execute(f"CREATE TRIGGER workbench_change AFTER INSERT OR UPDATE OR DELETE ON {table} "
                   f"FOR EACH ROW EXECUTE FUNCTION workbench_notify_change('{topic}')")


def downgrade():
    for table in TABLES:
        op.execute(f"DROP TRIGGER workbench_change ON {table}")
    op.execute("DROP FUNCTION workbench_notify_change()")
