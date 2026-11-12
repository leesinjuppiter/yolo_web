"""Active-learning inputs must enter the existing training boundary unchanged."""
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.training.schemas import TrainingConfig


def configuration(**updates):
    return {"name": "固定输入训练", "datasetId": str(uuid4()), "task": "detect", "modelId": "yolo11n",
            "deviceId": "cpu", "epochs": 1, "batchSize": 1, "imageSize": 64, "optimizer": "AdamW",
            "learningRate": .001, "finalLearningRate": .01, "seed": 42, "patience": 0,
            "augmentation": "standard", **updates}


@pytest.mark.parametrize("keys", [("iterationId",), ("manifestId",), ("manifestDigest",),
                                 ("iterationId", "manifestId"), ("iterationId", "manifestDigest"),
                                 ("manifestId", "manifestDigest")])
def test_partial_manifest_references_are_rejected(keys):
    refs = {"iterationId": str(uuid4()), "manifestId": str(uuid4()), "manifestDigest": "a" * 64}
    with pytest.raises(ValidationError, match="同时提供"):
        TrainingConfig.model_validate(configuration(**{key: refs[key] for key in keys}))


@pytest.mark.parametrize("active", [False, True])
def test_unified_preflight_uses_correct_input_source(monkeypatch, active):
    from app.training import service
    from app.active_learning import manifests
    calls = []
    monkeypatch.setattr(service, "_model_for", lambda db, config: None)
    monkeypatch.setattr(service, "inspect_dataset", lambda *args: calls.append("dataset") or {"source": "dataset"})
    monkeypatch.setattr(manifests, "validate_training_manifest", lambda *args: calls.append("manifest") or {"source": "manifest"})
    refs = {"iterationId": str(uuid4()), "manifestId": str(uuid4()), "manifestDigest": "a" * 64} if active else {}
    config = TrainingConfig.model_validate(configuration(**refs))
    result = service.preflight(object(), config)
    expected = "manifest" if active else "dataset"
    assert result == {"source": expected} and calls == [expected]


def test_worker_materializes_submitted_manifest_not_live_dataset(monkeypatch, tmp_path):
    from app.training import worker
    from app.active_learning import manifests
    calls = []
    task = SimpleNamespace(config={"manifestId": str(uuid4()), "manifestDigest": "b" * 64},
                           cancel_requested=False)
    @contextmanager
    def fake_session(_):
        yield "db"
    @contextmanager
    def edit(_):
        yield None, task
    def materialize(db, manifest_id, destination, **kwargs):
        calls.append((db, manifest_id, destination, kwargs["expected_digest"]))
        kwargs["check_cancel"]()
        return {"data_path": str(destination / "data.yaml"), "manifest_path": str(destination / "manifest.json"),
                "image_count": 12, "class_count": 1, "digest": "frozen"}
    monkeypatch.setattr(worker, "Session", fake_session)
    monkeypatch.setattr(worker, "engine", lambda: None)
    monkeypatch.setattr(worker, "_edit", edit)
    monkeypatch.setattr(manifests, "materialize_manifest", materialize)
    monkeypatch.setattr(worker, "prepare_snapshot", lambda *a, **kw: pytest.fail("不应扫描live数据集"))
    checks = []
    result = worker._prepare(task, tmp_path, lambda: checks.append(True))
    assert calls == [("db", task.config["manifestId"], tmp_path / "input", "b" * 64)]
    assert result["data_path"] == "input/data.yaml" and task.dataset_image_count == 12
    assert task.snapshot["digest"] == "frozen" and len(checks) >= 2


class Connection:
    def __init__(self, answers):
        self.answers = iter(answers)
        self.keys, self.released = [], []
        self.closed = False
    def execution_options(self, **kwargs):
        return self
    def __enter__(self):
        return self
    def __exit__(self, *_):
        self.closed = True
    def scalar(self, sql, parameters):
        self.keys.append(parameters["key"])
        return next(self.answers)
    def execute(self, sql, parameters):
        self.released.append(parameters["key"])


def test_gpu_slots_distinguish_devices_and_release_after_failure(monkeypatch):
    from app.training import compute
    connections = [Connection([True]), Connection([True])]
    created = iter(connections)
    monkeypatch.setattr(compute, "engine", lambda: SimpleNamespace(connect=lambda: next(created)))
    for device in ("cuda:0", "cuda:1"):
        with pytest.raises(RuntimeError, match="failed"):
            with compute.device_slot(device, lambda: None):
                raise RuntimeError("failed")
    assert connections[0].keys != connections[1].keys
    assert all(item.released == item.keys and item.closed for item in connections)


def test_cancel_while_waiting_does_not_unlock_other_owners_slot(monkeypatch):
    from app.training import compute
    connection = Connection([False])
    monkeypatch.setattr(compute, "engine", lambda: SimpleNamespace(connect=lambda: connection))
    def cancel():
        raise RuntimeError("canceled")
    with pytest.raises(RuntimeError, match="canceled"):
        with compute.device_slot("cuda:0", cancel):
            pytest.fail("不得进入计算")
    assert connection.closed and connection.released == []


def test_cancel_immediately_after_acquiring_releases_slot(monkeypatch):
    from app.training import compute
    connection = Connection([True])
    monkeypatch.setattr(compute, "engine", lambda: SimpleNamespace(connect=lambda: connection))
    def cancel():
        raise RuntimeError("canceled")
    with pytest.raises(RuntimeError, match="canceled"):
        with compute.device_slot("cuda:0", cancel):
            pytest.fail("不得进入计算")
    assert connection.closed and connection.released == connection.keys


def test_cpu_does_not_acquire_gpu_slot(monkeypatch):
    from app.training import compute
    monkeypatch.setattr(compute, "engine", lambda: pytest.fail("CPU不应获取GPU锁"))
    with compute.device_slot("cpu", lambda: None):
        pass
