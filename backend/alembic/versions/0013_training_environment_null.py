"""Allow training environment initialization from JSON null."""

from alembic import op

revision = "0013_training_environment_null"
down_revision = "0012_change_notifications"
branch_labels = None
depends_on = None


def _replace_function(normalize_nulls):
    environment = "COALESCE(item->'environment', '{}'::jsonb)"
    if normalize_nulls:
        environment = "COALESCE(NULLIF(item->'environment', 'null'::jsonb), '{}'::jsonb)"
    previous_environment = environment.replace("item->", "previous->")
    op.execute(f"""
    CREATE OR REPLACE FUNCTION workbench_notify_change() RETURNS trigger LANGUAGE plpgsql AS $$
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
             ({environment} - 'resourceSample') =
             ({previous_environment} - 'resourceSample')
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


def upgrade():
    _replace_function(normalize_nulls=True)


def downgrade():
    _replace_function(normalize_nulls=False)
