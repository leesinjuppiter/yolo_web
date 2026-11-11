import json
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.database import engine
from app.evaluation.models import EvaluationRun
from app.evaluation.snapshot import prepare_test_snapshot
from app.models.training_versions import ModelVersion
from app.training.models import TrainingTask
from app.training.repository import task_dir
from test_dataset_api import client


def _write_snapshot(root, duplicate=False):
    classes = [{"id": "coal", "name": "coal", "index": 0}]
    rows = []
    for split in ("train", "val", "test"):
        image = b"same" if duplicate and split != "val" else split.encode()
        label = b"0 .5 .5 .2 .2"
        entry = {"image_path": f"images/{split}/a.png", "label_path": f"labels/{split}/a.txt",
                 "image_sha256": sha256(image).hexdigest(), "label_sha256": sha256(label).hexdigest(),
                 "split": split}
        for kind, payload in (("image", image), ("label", label)):
            path = root / entry[kind + "_path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        rows.append(entry)
    data = "\n".join(json.dumps(row) for row in rows).encode()
    (root / "samples.jsonl").write_bytes(data)
    manifest = json.dumps({"classes": classes, "samples_path": "samples.jsonl",
                           "samples_sha256": sha256(data).hexdigest()}).encode()
    (root / "manifest.json").write_bytes(manifest)
    return {"digest": sha256(manifest).hexdigest(), "split_counts": {"train": 1, "val": 1, "test": 1}}


def test_test_snapshot_freezes_inputs_and_rejects_tampering(monkeypatch, tmp_path):
    task = SimpleNamespace(id=str(uuid4()), config={"task": "obb"})
    root = tmp_path / "source"
    task.snapshot = _write_snapshot(root)
    monkeypatch.setattr("app.evaluation.snapshot.task_dir", lambda _: tmp_path)
    root.rename(tmp_path / "input")
    prepared = prepare_test_snapshot(task, tmp_path / "frozen")
    assert prepared["sampleCount"] == 1 and prepared["classNames"] == ["coal"]
    assert not (tmp_path / "frozen/images/train").exists()
    (tmp_path / "input/images/test/a.png").write_bytes(b"modified")
    with pytest.raises(ValueError, match="校验失败"):
        prepare_test_snapshot(task, tmp_path / "tampered")
    assert not (tmp_path / "tampered").exists()


def test_test_snapshot_blocks_train_test_leakage(monkeypatch, tmp_path):
    root = tmp_path / "input"
    task = SimpleNamespace(id=str(uuid4()), config={"task": "detect"},
                           snapshot=_write_snapshot(root, duplicate=True))
    monkeypatch.setattr("app.evaluation.snapshot.task_dir", lambda _: tmp_path)
    with pytest.raises(ValueError, match="完全重复"):
        prepare_test_snapshot(task, tmp_path / "frozen")


@pytest.fixture
def registry_version(client):
    task_id = str(uuid4())
    folder = task_dir(task_id)
    snapshot = _write_snapshot(folder / "input")
    weight = folder / "best.pt"
    weight.write_bytes(b"trusted-test-checkpoint")
    digest = sha256(weight.read_bytes()).hexdigest()
    with Session(engine()) as db, db.begin():
        task = TrainingTask(id=task_id, dataset_id=str(uuid4()), dataset_name="immutable-source",
                            dataset_image_count=3, dataset_class_count=1,
                            config={"name": f"registry-{uuid4()}", "task": "detect", "deviceId": "cpu"},
                            model_name="YOLO11n", architecture="yolo11n", status="succeeded",
                            snapshot=snapshot, metrics={"map50": .8},
                            artifacts=[{"id": "best", "name": "best.pt", "path": "best.pt",
                                        "kind": "checkpoint", "sha256": digest, "sizeBytes": weight.stat().st_size}])
        db.add(task)
        db.flush()
        version = ModelVersion(task_id=task_id, artifact_id="best", sha256=digest)
        db.add(version)
        db.flush()
        version_id = version.id
    yield version_id
    with Session(engine()) as db, db.begin():
        db.execute(delete(EvaluationRun).where(EvaluationRun.version_id == version_id))
        db.execute(delete(ModelVersion).where(ModelVersion.id == version_id))
        db.execute(delete(TrainingTask).where(TrainingTask.id == task_id))


def test_registry_metadata_archive_and_evaluation_idempotency(client, registry_version):
    version_id = registry_version
    result = client.get("/api/models", params={"task": "detect"}).json()
    assert any(row["id"] == version_id for row in result["items"])
    item = client.get(f"/api/models/{version_id}").json()
    assert item["validationStatus"] == "unverified" and item["evaluation"] is None
    assert item["trainingMetrics"]["map50"] == .8
    updated = client.patch(f"/api/models/{version_id}", json={"displayName": "coal-model", "description": "test"})
    assert updated.status_code == 200 and updated.json()["name"] == "coal-model"
    key = str(uuid4())
    request = {"versionId": version_id, "deviceId": "cpu", "imgsz": 64}
    first = client.post("/api/evaluations", json=request, headers={"Idempotency-Key": key})
    assert first.status_code == 202, first.text
    second = client.post("/api/evaluations", json=request, headers={"Idempotency-Key": key})
    assert second.json()["id"] == first.json()["id"]
    assert client.post("/api/evaluations", json={**request, "imgsz": 96},
                       headers={"Idempotency-Key": key}).status_code == 409
    canceled = client.post(f"/api/evaluations/{first.json()['id']}/cancel")
    assert canceled.json()["status"] == "canceled"
    assert client.post(f"/api/models/{version_id}/archive").json()["lifecycle"] == "archived"
    assert client.post("/api/evaluations", json=request).status_code == 409
    assert client.post(f"/api/models/{version_id}/restore").json()["lifecycle"] == "candidate"


def test_compare_rejects_duplicates_and_does_not_rank_training_metrics(client, registry_version):
    payload = {"versionIds": [registry_version, registry_version], "baselineId": registry_version}
    assert client.post("/api/models/compare", json=payload).status_code == 422


def test_compare_requires_matching_protocol_for_deltas(monkeypatch):
    from app.models.registry import compare
    from app.evaluation.schemas import CompareRequest
    first, second = str(uuid4()), str(uuid4())
    models = {
        first: {"taskType": "detect", "evaluation": {"report": {
            "protocolDigest": "same", "metrics": {"map50": .698}}}},
        second: {"taskType": "detect", "evaluation": {"report": {
            "protocolDigest": "same", "metrics": {"map50": .765}}}},
    }
    monkeypatch.setattr("app.models.registry.detail", lambda _db, key: models[key])
    request = CompareRequest(versionIds=[first, second], baselineId=first)
    result = compare(None, request)
    assert result["comparable"]
    assert result["rows"][0]["deltas"][second] == pytest.approx(.067)
    models[second]["evaluation"]["report"]["protocolDigest"] = "different"
    result = compare(None, request)
    assert not result["comparable"]
    assert result["rows"][0]["deltas"][second] is None
    models[second]["evaluation"] = None
    assert not compare(None, request)["comparable"]


def test_evaluation_log_tail_hides_paths_and_secrets(tmp_path):
    from app.evaluation.worker import safe_tail
    path = tmp_path / "stdout.log"
    path.write_text('File "/root/private/model.pt", line 2\npassword=do-not-return\nRuntimeError: invalid shape\n')
    tail = "\n".join(safe_tail(path))
    assert "private" not in tail and "do-not-return" not in tail
    assert "invalid shape" in tail
