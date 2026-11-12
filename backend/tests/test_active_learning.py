import json
from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

from PIL import Image
import pytest
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.active_learning import manifests, repository, storage
from app.active_learning.models import Candidate, Iteration, RecommendationTask, TrainingManifest
from app.active_learning.review import assert_trainable, upsert_candidate
from app.active_learning.schemas import RecommendationRequest
from app.core.database import engine
from app.dataset.models import DatasetImage
from app.dataset.repository import Conflict
from app.models.training_versions import ModelVersion
from app.training.models import TrainingTask
from app.training.repository import task_dir
from app.training.snapshot import prepare_snapshot
from test_dataset_api import client


def test_recommendation_thresholds_and_required_diagnostic():
    identifier = str(uuid4())
    assert RecommendationRequest(iterationId=identifier, strategy="low_confidence").maxConfidence == .5
    with pytest.raises(ValidationError, match="val 诊断"):
        RecommendationRequest(iterationId=identifier)
    with pytest.raises(ValidationError, match="保留阈值"):
        RecommendationRequest(iterationId=identifier, strategy="low_confidence", retainConfidence=.6)


@pytest.mark.parametrize("split,excluded,sha", [("val", None, "a"), ("test", None, "a"),
    ("train", None, "protected"), (None, True, "a")])
def test_protected_images_cannot_enter_training(split, excluded, sha):
    iteration = SimpleNamespace(dataset_id="dataset", source={"samples": [{"split": "val", "image_sha256": "protected"}]})
    image = SimpleNamespace(dataset_id="dataset", split=split, excluded_at=excluded)
    with pytest.raises(Conflict):
        assert_trainable(iteration, image, sha)


def test_review_is_version_and_class_specific():
    classes = [{"id": "coal", "name": "coal"}]
    image = SimpleNamespace(version=2, split="train", excluded_at=None)
    candidate = SimpleNamespace(review={"version": 2, "classDigest": storage.digest(classes)})
    assert repository.review_valid(candidate, image, classes)
    image.version = 3
    assert not repository.review_valid(candidate, image, classes)
    image.version = 2
    assert not repository.review_valid(candidate, image, [{"id": "coal", "name": "renamed"}])


def test_fixed_source_rejects_file_tampering(monkeypatch, tmp_path):
    root = tmp_path / "input"
    root.mkdir()
    (root / "a.txt").write_bytes(b"original")
    monkeypatch.setattr(storage, "task_dir", lambda _: tmp_path)
    sample = {"label_path": "a.txt", "label_sha256": sha256(b"original").hexdigest()}
    assert storage.source_bytes({"taskId": "id"}, sample, "label") == b"original"
    (root / "a.txt").write_bytes(b"changed")
    with pytest.raises(ValueError, match="校验失败"):
        storage.source_bytes({"taskId": "id"}, sample, "label")
    sample["label_path"] = "../../outside"
    with pytest.raises(ValueError, match="越界"):
        storage.source_bytes({"taskId": "id"}, sample, "label")


def test_original_samples_deduplicate_but_reject_conflicting_labels():
    base = {"image_id": "a", "image_sha256": "same", "label_sha256": "label", "split": "train",
            "status": "annotated", "name": "a"}
    iteration = SimpleNamespace(source={"samples": [base, {**base, "image_id": "b"}], "classes": []})
    samples, excluded = manifests._samples(None, iteration, [])
    assert len(samples) == 1 and excluded == 1
    iteration.source["samples"][1]["label_sha256"] = "other"
    with pytest.raises(Conflict, match="不同标注"):
        manifests._samples(None, iteration, [])


def test_manual_add_preserves_model_predictions_and_reasons():
    prediction = {"id": "prediction", "type": "bbox"}
    candidate = SimpleNamespace(data={"predictions": [prediction], "reasons": ["low_confidence"],
        "taskIds": ["recommendation"], "unsupportedPrediction": False})
    class Database:
        def scalar(self, _):
            return candidate
        def flush(self):
            pass
    result = upsert_candidate(Database(), SimpleNamespace(id="iteration"), "image", "training",
                              {"reasons": ["manual_revision"]})
    assert result.data["predictions"] == [prediction]
    assert result.data["reasons"] == ["low_confidence", "manual_revision"]
    assert result.data["taskIds"] == ["recommendation"]


def _png(color):
    output = BytesIO()
    Image.new("RGB", (64, 64), color=color).save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def active_iteration(client):
    dataset_id = client.post("/api/datasets", json={"name": str(uuid4()), "task_type": "detect"}).json()["id"]
    url = "/api/datasets/" + dataset_id
    label = {"id": str(uuid4()), "name": "coal", "color": "#123456"}
    annotation = {"id": str(uuid4()), "type": "bbox", "class_id": label["id"], "source": "manual",
                  "bbox": {"x": 5, "y": 5, "width": 20, "height": 20}}
    images = []
    for index, color in enumerate(("red", "green", "blue", "yellow")):
        row = client.post(url + "/images", files={"files": (f"{index}.png", _png(color), "image/png")}).json()["images"][-1]
        images.append(row)
        if index < 3:
            saved = client.put(f"{url}/images/{row['id']}/annotations", json={
                "version": row["version"], "status": "annotated", "classes": [label], "annotations": [annotation]})
            assert saved.status_code == 200, saved.text
    client.patch(url + "/splits", json={"splits": {images[i]["id"]: split for i, split in enumerate(("train", "val", "test"))}})
    task_id = str(uuid4())
    with Session(engine()) as db:
        snapshot = prepare_snapshot(db, dataset_id, "detect", task_dir(task_id) / "input")
    weight = task_dir(task_id) / "best.pt"
    weight.write_bytes(b"test-checkpoint-not-loaded")
    with Session(engine()) as db, db.begin():
        db.add(TrainingTask(id=task_id, dataset_id=dataset_id, dataset_name="baseline", dataset_image_count=3,
            dataset_class_count=1, config={"name": "baseline", "task": "detect", "deviceId": "cpu"},
            model_name="YOLO11n", architecture="yolo11n", status="succeeded", snapshot=snapshot,
            artifacts=[{"id": "best", "path": "best.pt"}]))
        db.flush()
        version = ModelVersion(task_id=task_id, artifact_id="best", sha256=sha256(weight.read_bytes()).hexdigest())
        db.add(version)
        db.flush()
        version_id = version.id
    response = client.post("/api/active-learning/iterations", json={"name": "round", "goal": "missed coal",
        "datasetId": dataset_id, "baselineVersionId": version_id})
    assert response.status_code == 201, response.text
    iteration = response.json()
    yield {"iteration": iteration, "images": images, "label": label, "annotation": annotation, "url": url}
    with Session(engine()) as db, db.begin():
        ids = select(Iteration.id).where(Iteration.dataset_id == dataset_id)
        db.execute(delete(TrainingTask).where(TrainingTask.config["iterationId"].astext == iteration["id"]))
        for model in (Candidate, TrainingManifest, RecommendationTask):
            db.execute(delete(model).where(model.iteration_id.in_(ids)))
        db.execute(delete(Iteration).where(Iteration.dataset_id == dataset_id))
        db.execute(delete(ModelVersion).where(ModelVersion.id == version_id))
        db.execute(delete(TrainingTask).where(TrainingTask.id == task_id))
    assert client.delete(url).status_code == 204


def test_review_manifest_and_training_entry_protect_drafts(client, active_iteration, monkeypatch, tmp_path):
    context = active_iteration
    iteration = context["iteration"]
    root = "/api/active-learning"
    add = client.post(f"{root}/iterations/{iteration['id']}/candidates", json={"imageIds": [context["images"][3]["id"]]})
    assert add.status_code == 200, add.text
    with Session(engine()) as db:
        candidate_id = db.scalar(select(Candidate.id).where(Candidate.iteration_id == iteration["id"]))
    client.post(f"{root}/iterations/{iteration['id']}/selection", json={"candidateIds": [candidate_id], "selected": True})
    prepare_url = f"{root}/iterations/{iteration['id']}/prepare-training"
    assert client.post(prepare_url).status_code == 409
    image = client.get(context["url"]).json()["images"][-1]
    reviewed = client.post(f"{root}/candidates/{candidate_id}/review", json={"version": image["version"],
        "annotations": [context["annotation"]], "status": "annotated", "negativeConfirmed": False})
    assert reviewed.status_code == 200, reviewed.text
    prepared = client.post(prepare_url)
    assert prepared.status_code == 200, prepared.text
    data = prepared.json()
    assert data["counts"]["new"] == 1 and data["counts"]["total"] == 2
    from app.training.catalog import ModelOption
    monkeypatch.setattr("app.training.service._model_for", lambda *_: ModelOption(
        "test", "test", "yolo11n", "detect", "test.pt", True))
    config = {"name": "active-" + str(uuid4()), "datasetId": iteration["datasetId"], "task": "detect",
        "modelId": "version:" + iteration["baselineVersionId"], "deviceId": "cpu", "epochs": 1,
        "batchSize": 1, "imageSize": 64, "optimizer": "SGD", "learningRate": .01,
        "finalLearningRate": .01, "seed": 0, "patience": 1, "augmentation": "standard",
        **{key: data[key] for key in ("iterationId", "manifestId", "manifestDigest")}}
    preflight = client.post("/api/training/preflight", json=config)
    assert preflight.status_code == 200, preflight.text
    assert preflight.json()["imageCount"] == 4
    with Session(engine()) as db:
        snapshot = manifests.materialize_manifest(db, data["manifestId"], tmp_path / "frozen",
                                                  expected_digest=data["manifestDigest"])
    samples = [json.loads(line) for line in (tmp_path / "frozen/samples.jsonl").read_text().splitlines()]
    assert snapshot["split_counts"] == {"train": 2, "val": 1, "test": 1}
    assert {entry["image_id"] for entry in samples if entry["split"] == "train"} == {
        context["images"][0]["id"], context["images"][3]["id"]}
    created = client.post("/api/training", json=config)
    assert created.status_code == 202, created.text
    latest = client.get(context["url"]).json()["images"][-1]
    client.put(f"{context['url']}/images/{latest['id']}/annotations", json={
        "version": latest["version"], "classes": [context["label"]], "status": "negative", "annotations": []})
    config["name"] += "-changed"
    assert client.post("/api/training", json=config).status_code == 409
