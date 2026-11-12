import json
from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from app.active_learning.models import Iteration
from app.active_learning.repository import reference_response
from app.core.config import data_dir
from app.core.database import get_db
from app.evaluation.images import frozen_image


def write_frozen(root):
    image_id = str(uuid4())
    image = BytesIO()
    Image.new("RGB", (80, 40), "red").save(image, format="PNG")
    content = image.getvalue()
    source = root / "input/images/val" / (image_id + ".png")
    source.parent.mkdir(parents=True)
    source.write_bytes(content)
    sample = {"image_id": image_id, "image_path": "images/val/" + source.name,
              "image_sha256": sha256(content).hexdigest()}
    manifest = {"samples": [sample], "classes": [], "split": "val", "task": "detect"}
    (root / "input/manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    digest = sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return image_id, source, content, digest, sample


def test_frozen_content_and_thumbnail_ignore_live_image(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path / "storage"))
    data_dir.cache_clear()
    try:
        identifier, source, content, digest, sample = write_frozen(tmp_path / "evaluation")
        legacy = data_dir() / "thumbnails" / (identifier + ".jpg")
        legacy.parent.mkdir(parents=True)
        Image.new("RGB", (80, 40), "blue").save(legacy)
        assert frozen_image(tmp_path / "evaluation", digest, identifier).read_bytes() == content
        thumb = frozen_image(tmp_path / "evaluation", digest, identifier, True)
        assert thumb.stem == sample["image_sha256"]
        with Image.open(thumb) as image:
            red, green, blue = image.getpixel((10, 10))
            assert red > 200 and blue < 30
        source.write_bytes(b"tampered")
        with pytest.raises(ValueError, match="校验失败"):
            frozen_image(tmp_path / "evaluation", digest, identifier, True)
    finally:
        data_dir.cache_clear()


def test_completed_evaluation_image_routes_serve_snapshot(monkeypatch, tmp_path):
    from app.api.evaluation import router
    from app.evaluation import service
    identifier, source, content, digest, _ = write_frozen(tmp_path / "evaluation")
    row = SimpleNamespace(id=str(uuid4()), status="succeeded", report={"snapshot": {"digest": digest}})
    monkeypatch.setattr(service, "get_run", lambda *_: row)
    monkeypatch.setattr(service, "evaluation_dir", lambda _: tmp_path / "evaluation")
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path / "storage"))
    data_dir.cache_clear()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: None
    try:
        with TestClient(app) as client:
            root = f"/api/evaluations/{row.id}/images/{identifier}"
            response = client.get(root + "/content")
            assert response.status_code == 200 and response.content == content
            thumb = client.get(root + "/thumbnail")
            assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"
    finally:
        data_dir.cache_clear()


def test_reference_metadata_and_geometry_never_read_live_dataset_image():
    label = {"id": "coal", "name": "coal", "index": 0}
    ground_truth = [{"id": "gt", "class_id": "coal", "type": "bbox",
                     "bbox": {"x": 1, "y": 2, "width": 3, "height": 4}}]
    row = SimpleNamespace(id="candidate", iteration_id="iteration", task_id="task", image_id="image",
        data={"name": "frozen.png", "evaluationId": "evaluation", "reasons": ["false_negative"],
              "diagnostic": {"width": 80, "height": 40, "annotationVersion": 5, "groundTruth": ground_truth,
                             "predictions": [{"classIndex": 0, "type": "bbox", "confidence": .5,
                                              "bbox": {"x": 5, "y": 6, "width": 7, "height": 8}}]}})
    class Database:
        def scalar(self, query):
            assert query.column_descriptions[0]["entity"] is Iteration
            return SimpleNamespace(source={"classes": [label]})
    # Only the iteration's frozen class map is queried. No live DatasetImage is required.
    result = reference_response(Database(), row)
    assert result["image"]["width"] == 80 and result["image"]["version"] == 5
    assert result["image"]["src"] == "/api/evaluations/evaluation/images/image/content"
    assert result["image"]["annotations"] == ground_truth
    assert result["predictions"][0]["class_id"] == "coal"
    summary = reference_response(Database(), row, detail=False)
    assert summary["image"]["annotations"] == [] and summary["predictions"] == []
