import json
from types import SimpleNamespace

from PIL import Image
import pytest

from app.training.previews import generate_previews, read_previews
from app.training.runner_io import artifact_manifest


@pytest.mark.parametrize("count", [1, 20])
@pytest.mark.parametrize("task,annotation", [
    ("detect", {"type": "bbox", "bbox": {"x": 20, "y": 30, "width": 60, "height": 40}}),
    ("segment", {"type": "polygon", "polygon": [[20, 30], [80, 30], [80, 70], [20, 70]]}),
    ("obb", {"type": "obb", "obb": {"cx": 50, "cy": 50, "width": 60, "height": 40, "angle": 25}}),
    ("classify", {"type": "classify"}),
])
def test_single_previews_keep_original_size_and_pair_labels(tmp_path, monkeypatch, task, annotation, count):
    import ultralytics

    frozen = tmp_path / "input"
    frozen.mkdir()
    Image.new("RGB", (300, 180), "#303030").save(frozen / "one.png")
    sample = {"name": "原始名称.png", "width": 300, "height": 180, "image_path": "one.png",
              "annotations": [{**annotation, "class_id": "object"}]}
    rows = [{**sample, "split": split} for split in ("train", "test")]
    rows.extend({**sample, "split": "val"} for _ in range(count))
    (frozen / "samples.jsonl").write_text("\n".join(json.dumps(row) for row in rows))
    (frozen / "manifest.json").write_text(json.dumps({"classes": [{"id": "object", "name": "coal", "index": 0}]}))
    (tmp_path / "invocation.json").write_text(json.dumps({"arguments": {"imgsz": 320}}))
    calls = []

    def predict(**kwargs):
        calls.append(kwargs)
        def save(filename):
            with Image.open(frozen / "one.png") as image:
                image.convert("RGB").save(filename)
        return iter(SimpleNamespace(save=save) for _ in kwargs["source"])

    monkeypatch.setattr(ultralytics, "YOLO", lambda checkpoint: SimpleNamespace(predict=predict))
    original = (frozen / "one.png").read_bytes()
    records = generate_previews(tmp_path)
    assert read_previews(tmp_path) == records
    assert len(records) == min(count, 16) and records[0]["name"] == "原始名称.png"
    assert calls[0]["source"] == [str(frozen / "one.png")] * min(count, 16)
    assert calls[0]["batch"] == 1 and calls[0]["device"] == "cpu"
    artifacts = artifact_manifest(tmp_path)
    assert {item["id"] for item in artifacts if item["kind"] == "preview"} == {
        item[key] for item in records for key in ("artifactId", "groundTruthArtifactId")}
    for item in artifacts:
        if item["kind"] == "preview":
            with Image.open(tmp_path / item["path"]) as image:
                assert image.size == (300, 180)
    assert original == (frozen / "one.png").read_bytes()


def test_missing_preview_manifest_keeps_existing_batch_artifacts(tmp_path):
    (tmp_path / "output").mkdir()
    for name in ("val_batch0_pred.jpg", "val_batch0_labels.jpg"):
        Image.new("RGB", (64, 64)).save(tmp_path / "output" / name)
    assert read_previews(tmp_path) == []
    assert {item["id"] for item in artifact_manifest(tmp_path)} == {"preview-prediction", "preview-labels"}


def test_preview_manifest_cannot_register_paths_outside_preview_directory(tmp_path):
    folder = tmp_path / "output/previews"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps([{"id": "../../outside"}]))
    assert artifact_manifest(tmp_path) == []
