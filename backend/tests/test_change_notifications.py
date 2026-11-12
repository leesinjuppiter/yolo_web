import asyncio
import json
import os

import psycopg
import pytest
from sqlalchemy.engine import make_url

from app.notifications.service import ChangeFeed


@pytest.fixture
def connections():
    value = os.environ.get("WORKBENCH_TEST_DATABASE_URL")
    if not value:
        pytest.skip("需要已迁移的独立 PostgreSQL 测试库")
    url = make_url(value).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(url, autocommit=True) as listener, psycopg.connect(url) as writer:
        listener.execute("LISTEN workbench_changes")
        yield listener, writer


def received(listener):
    return [json.loads(item.payload) for item in listener.notifies(timeout=.2)]


def temporary_table(writer, name, columns, topic):
    writer.execute(f"CREATE TEMP TABLE {name} ({columns})")
    writer.execute(f"CREATE TRIGGER test_change AFTER INSERT OR UPDATE OR DELETE ON {name} "
                   f"FOR EACH ROW EXECUTE FUNCTION workbench_notify_change('{topic}')")
    writer.commit()


def test_notifications_only_after_commit_and_no_private_payload(connections):
    listener, writer = connections
    temporary_table(writer, "dataset_images", "id text, dataset_id text, annotations jsonb", "datasets")
    writer.execute("INSERT INTO dataset_images VALUES ('image', 'dataset', '{\"secret\":true}')")
    assert received(listener) == []
    writer.rollback()
    assert received(listener) == []
    writer.execute("INSERT INTO dataset_images VALUES ('image', 'dataset', '{\"secret\":true}')")
    writer.execute("INSERT INTO dataset_images VALUES ('image2', 'dataset', '{}')")
    writer.commit()
    assert received(listener) == [{"topic": "datasets", "table": "dataset_images", "id": "dataset"}]
    writer.execute("DELETE FROM dataset_images")
    writer.commit()
    assert received(listener)[0]["id"] == "dataset"


def test_training_heartbeat_suppression_resource_routing_and_log_id(connections):
    listener, writer = connections
    temporary_table(writer, "training_tasks", "id text, dataset_id text, heartbeat_at int, worker_token text, environment jsonb, epoch int", "training")
    writer.execute("INSERT INTO training_tasks VALUES ('task','dataset',1,'worker','{\"resourceSample\":1}',0)")
    writer.commit()
    assert received(listener)[0]["id"] == "task"
    writer.execute("UPDATE training_tasks SET heartbeat_at=2")
    writer.commit()
    assert received(listener) == []
    writer.execute("UPDATE training_tasks SET environment='{\"resourceSample\":2}',heartbeat_at=3")
    writer.commit()
    assert received(listener)[0]["topic"] == "resources"
    writer.execute("UPDATE training_tasks SET epoch=1")
    writer.commit()
    assert received(listener)[0]["topic"] == "training"
    temporary_table(writer, "training_logs", "task_id text, sequence int", "training")
    writer.execute("INSERT INTO training_logs VALUES ('task',1)")
    writer.commit()
    assert received(listener)[0]["id"] == "task"


@pytest.mark.parametrize("environment", [None, "null"], ids=["sql_null", "json_null"])
def test_training_environment_initialization_from_null(connections, environment):
    listener, writer = connections
    temporary_table(writer, "training_tasks", "id text, heartbeat_at int, environment jsonb", "training")
    writer.execute("INSERT INTO training_tasks VALUES ('task',1,%s::jsonb)", (environment,))
    writer.commit()
    assert received(listener)[0]["topic"] == "training"
    writer.execute('UPDATE training_tasks SET environment=\'{"device":"cpu"}\',heartbeat_at=2')
    writer.commit()
    assert received(listener) == [{"topic": "training", "table": "training_tasks", "id": "task"}]
    writer.execute('UPDATE training_tasks SET environment=\'{"device":"cpu","resourceSample":1}\'')
    writer.commit()
    assert received(listener)[0]["topic"] == "resources"
    writer.execute("UPDATE training_tasks SET heartbeat_at=3")
    writer.commit()
    assert received(listener) == []


def test_report_lease_does_not_refresh_page_and_kind_is_preserved(connections):
    listener, writer = connections
    temporary_table(writer, "dataset_analysis_jobs", "dataset_id text, kind text, lease_until int, claim_token text, completed int", "reports")
    writer.execute("INSERT INTO dataset_analysis_jobs VALUES ('dataset','quality',1,'worker',0)")
    writer.commit()
    assert received(listener)[0]["kind"] == "quality"
    writer.execute("UPDATE dataset_analysis_jobs SET lease_until=2")
    writer.commit()
    assert received(listener) == []
    writer.execute("UPDATE dataset_analysis_jobs SET completed=1")
    writer.commit()
    assert received(listener)[0]["id"] == "dataset"


def test_stream_fanout_overflow_resync_and_disconnect_cleanup():
    async def run():
        feed = ChangeFeed()
        feed.ready = True
        a, b = feed.stream(), feed.stream()
        assert "retry:" in await anext(a)
        assert "event: sync" in await anext(a)
        await anext(b); await anext(b)
        feed.publish("change", {"topic": "exports", "id": "job"})
        assert "job" in await anext(a)
        assert "job" in await anext(b)
        for _ in range(129):
            feed.publish("change", {"topic": "models"})
        assert "event: sync" in await anext(a)
        await a.aclose(); await b.aclose()
        assert not feed.clients
    asyncio.run(run())
