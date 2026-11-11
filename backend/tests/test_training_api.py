from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.core.database import engine
from app.models.training_versions import ModelVersion
from app.training.models import TrainingTask
from app.training.repository import task_dir
from app.training.snapshot import prepare_snapshot
from test_dataset_api import client


@pytest.fixture
def task_ids(client):
    ids = []
    yield ids
    with Session(engine()) as db, db.begin():
        db.execute(update(TrainingTask).where(TrainingTask.id.in_(ids)).values(
            parent_model_version_id=None, resume_from_task_id=None,
        ))
        db.execute(delete(ModelVersion).where(ModelVersion.task_id.in_(ids)))
        db.execute(delete(TrainingTask).where(TrainingTask.id.in_(ids)))


@pytest.fixture
def ready_dataset(client):
    dataset = client.post("/api/datasets", json={"name": f"training-{uuid4()}", "task_type": "detect"}).json()
    url = f"/api/datasets/{dataset['id']}"
    category = {"id": str(uuid4()), "name": "object", "color": "#135791"}
    for split, color in (("train", "red"), ("val", "blue")):
        buffer = BytesIO()
        Image.new("RGB", (64, 64), color).save(buffer, format="PNG")
        response = client.post(url + "/images", files={"files": (f"{split}.png", buffer.getvalue(), "image/png")},
                               data={"split": split})
        assert response.status_code == 200, response.text
        sample = next(image for image in response.json()["images"] if image["name"] == f"{split}.png")
        response = client.put(url + f"/images/{sample['id']}/annotations", json={
            "version": sample["version"], "status": "annotated", "classes": [category],
            "annotations": [{"id": str(uuid4()), "type": "bbox", "class_id": category["id"],
                             "bbox": {"x": 10, "y": 10, "width": 20, "height": 20}, "source": "manual"}],
        })
        assert response.status_code == 200, response.text
    yield client.get(url).json()
    assert client.delete(url).status_code in (204, 404)


def _config(dataset_id):
    return {"name": f"training-{uuid4()}", "datasetId": dataset_id, "task": "detect", "modelId": "yolo11n",
            "deviceId": "cpu", "epochs": 3, "batchSize": 2, "imageSize": 64, "optimizer": "AdamW",
            "learningRate": 0.001, "finalLearningRate": 0.01, "seed": 42, "patience": 0,
            "amp": False, "augmentation": "standard"}


def _create(client, config, task_ids, key=None):
    response = client.post("/api/training", json=config, headers={"Idempotency-Key": key or str(uuid4())})
    assert response.status_code == 202, response.text
    result = response.json()
    if result["id"] not in task_ids:
        task_ids.append(result["id"])
    return result


def test_invalid_dataset_cannot_bypass_preflight(client, task_ids):
    dataset = client.post("/api/datasets", json={"name": f"empty-{uuid4()}", "task_type": "detect"}).json()
    try:
        response = client.post("/api/training", json=_config(dataset["id"]))
        assert response.status_code == 422, response.text
        assert "CLASSES_MISSING" in {issue["code"] for issue in response.json()["detail"]["issues"]}
    finally:
        client.delete(f"/api/datasets/{dataset['id']}")


def test_creation_rechecks_dataset_and_preserves_idempotency(client, ready_dataset, task_ids):
    config = _config(ready_dataset["id"])
    assert client.post("/api/training/preflight", json=config).json()["errors"] == []
    sample = ready_dataset["images"][0]
    url = f"/api/datasets/{ready_dataset['id']}/splits"
    assert client.patch(url, json={"splits": {sample["id"]: None}}).status_code == 200
    assert client.post("/api/training", json=config).status_code == 422
    assert client.patch(url, json={"splits": {sample["id"]: sample["split"]}}).status_code == 200
    key = str(uuid4())
    first = _create(client, config, task_ids, key)
    repeated = _create(client, config, task_ids, key)
    assert first["id"] == repeated["id"]
    assert first["config"]["freeze"] == first["config"]["workers"] == 0
    assert client.post("/api/training", json={**config, "epochs": 5},
                       headers={"Idempotency-Key": key}).status_code == 409


def test_training_dataset_options_do_not_include_images_or_annotations(client, ready_dataset):
    response = client.get("/api/training/datasets")
    assert response.status_code == 200, response.text
    item = next(row for row in response.json() if row["id"] == ready_dataset["id"])
    assert item["annotatedSplitCounts"] == {"train": 1, "val": 1, "test": 0}
    assert item["classCount"] == 1 and item["unassignedCount"] == 0
    assert "images" not in item and "annotations" not in item and item["revision"]


def test_registered_model_is_resolved_and_its_hash_is_rechecked(client, ready_dataset, task_ids):
    source = _create(client, _config(ready_dataset["id"]), task_ids)
    root = task_dir(source["id"])
    root.mkdir(parents=True)
    path = root / "best.pt"
    path.write_bytes(b"recorded-checkpoint")
    digest = sha256(path.read_bytes()).hexdigest()
    with Session(engine()) as db, db.begin():
        task = db.get(TrainingTask, source["id"])
        task.status = "succeeded"
        task.artifacts = [{"id": "best", "name": "best.pt", "path": "best.pt", "kind": "checkpoint",
                           "sha256": digest, "sizeBytes": path.stat().st_size}]
        task.snapshot = {"digest": "snapshot"}
    version_response = client.post(f"/api/training/{source['id']}/model-version")
    assert version_response.status_code == 200, version_response.text
    version = version_response.json()
    model_id = f"version:{version['id']}"
    options = client.get("/api/training/options").json()["models"]
    assert any(item["id"] == model_id and item["sourceType"] == "model_version" for item in options)
    child = _create(client, {**_config(ready_dataset["id"]), "modelId": model_id, "freeze": 2}, task_ids)
    assert child["parentModelVersionId"] == version["id"]
    assert client.delete(f"/api/training/{source['id']}").status_code == 409
    path.write_bytes(b"modified-checkpoint")
    response = client.post("/api/training/preflight", json={**_config(ready_dataset["id"]), "modelId": model_id})
    assert response.status_code == 409
    assert "校验失败" in response.text


def test_resume_rejects_queued_and_missing_checkpoints(client, ready_dataset, task_ids):
    task = _create(client, _config(ready_dataset["id"]), task_ids)
    endpoint = f"/api/training/{task['id']}/resume"
    assert client.post(endpoint, json={"name": f"resume-{uuid4()}"}).status_code == 409
    assert client.post(f"/api/training/{task['id']}/cancel").status_code == 200
    response = client.post(endpoint, json={"name": f"resume-{uuid4()}"})
    assert response.status_code == 409
    assert "快照" in response.text


def test_resume_creates_new_execution_with_original_snapshot_and_guards_source(client, ready_dataset, task_ids):
    import torch

    source = _create(client, _config(ready_dataset["id"]), task_ids)
    root = task_dir(source["id"])
    with Session(engine()) as db:
        snapshot = prepare_snapshot(db, ready_dataset["id"], "detect", root / "input")
    for field in ("data_path", "manifest_path"):
        snapshot[field] = Path(snapshot[field]).relative_to(root).as_posix()
    path = root / "last.pt"
    torch.save({"epoch": 0, "optimizer": {"state": {}, "param_groups": []},
                "train_args": {"epochs": 3}, "model": torch.nn.Linear(2, 1)}, path)
    digest = sha256(path.read_bytes()).hexdigest()
    with Session(engine()) as db, db.begin():
        task = db.get(TrainingTask, source["id"])
        task.status, task.phase, task.snapshot = "canceled", "canceled", snapshot
        task.artifacts = [{"id": "last", "name": "last.pt", "path": "last.pt", "kind": "checkpoint",
                           "sha256": digest, "sizeBytes": path.stat().st_size}]
    endpoint = f"/api/training/{source['id']}/resume"
    request = {"name": f"resumed-{uuid4()}", "batchSize": 1, "workers": 0, "amp": False}
    key = {"Idempotency-Key": str(uuid4())}
    response = client.post(endpoint, json=request, headers=key)
    assert response.status_code == 202, response.text
    resumed = response.json()
    task_ids.append(resumed["id"])
    assert resumed["id"] != source["id"] and resumed["resumeFromTaskId"] == source["id"]
    assert resumed["config"]["batchSize"] == 1 and resumed["config"]["epochs"] == 3
    assert client.post(endpoint, json=request, headers=key).json()["id"] == resumed["id"]
    assert client.post(endpoint, json={**request, "name": f"other-{uuid4()}"}).status_code == 409
    original = client.get(f"/api/training/{source['id']}").json()
    assert original["status"] == "canceled" and original["snapshotDigest"] == snapshot["digest"]
    assert client.delete(f"/api/training/{source['id']}").status_code == 409
    assert sha256(path.read_bytes()).hexdigest() == digest
