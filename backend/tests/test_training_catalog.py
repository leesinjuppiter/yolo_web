import json
from hashlib import sha256
from types import SimpleNamespace

import pytest

from app.training.catalog import available_models, resolve_model
from app.training.worker import _copy_model


def test_official_pretrained_choices_cover_five_sizes_and_four_tasks(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKBENCH_TRAINING_WEIGHTS_DIR", str(tmp_path))
    manifest = {}
    for task, suffix in {"detect": "", "segment": "-seg", "obb": "-obb", "classify": "-cls"}.items():
        for size in "nsmlx":
            name = f"yolo11{size}{suffix}.pt"
            (tmp_path / name).write_bytes(b"fixture-checkpoint")
            manifest[name] = {"task": task, "dataset": "fixture", "sizeBytes": 18,
                              "sha256": sha256(b"fixture-checkpoint").hexdigest(),
                              "url": "https://github.com/ultralytics/assets/releases/download/v8.4.0/" + name}
    (tmp_path / "official-yolo11.json").write_text(json.dumps({"models": manifest}))
    choices = available_models()
    scratch = [model for model in choices if not model.pretrained]
    assert len(scratch) == 20
    for task in ("detect", "segment", "obb", "classify"):
        assert len([model for model in scratch if model.task == task]) == 5
    pretrained = [model for model in choices if model.pretrained]
    assert len(pretrained) == 20
    for task in ("detect", "segment", "obb", "classify"):
        assert len([model for model in pretrained if model.task == task]) == 5
    assert all(model.source_type == "official_weights" and model.sha256 for model in pretrained)
    assert resolve_model("yolo11s-obb.pt").public()["pretrainingDataset"] == "fixture"


def test_only_existing_allowlisted_weights_are_offered(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKBENCH_TRAINING_WEIGHTS_DIR", str(tmp_path))
    (tmp_path / "yolo11s.pt").write_bytes(b"local")
    (tmp_path / "unknown.pt").write_bytes(b"unknown")
    choices = [model for model in available_models() if model.pretrained]
    assert [model.id for model in choices] == ["yolo11s.pt"]
    assert choices[0].source_type == "local_weights"
    with pytest.raises(ValueError):
        resolve_model("unknown.pt")


def test_official_weight_size_and_execution_digest_are_checked(monkeypatch, tmp_path):
    root = tmp_path / "weights"
    root.mkdir()
    monkeypatch.setenv("WORKBENCH_TRAINING_WEIGHTS_DIR", str(root))
    weight = root / "yolo11n.pt"
    weight.write_bytes(b"original")
    metadata = {"task": "detect", "dataset": "COCO", "sizeBytes": 8,
                "sha256": sha256(b"original").hexdigest()}
    (root / "official-yolo11.json").write_text(json.dumps({"models": {weight.name: metadata}}))
    target = tmp_path / "task"
    target.mkdir()
    task = SimpleNamespace(config={"modelId": "yolo11n.pt"}, snapshot=None)
    path, digest, pretrained = _copy_model(task, target, lambda: None)
    assert pretrained and path.read_bytes() == b"original" and digest == metadata["sha256"]
    weight.write_bytes(b"tampered")
    another = tmp_path / "another-task"
    another.mkdir()
    with pytest.raises(ValueError, match="校验"):
        _copy_model(task, another, lambda: None)
    weight.write_bytes(b"wrong size")
    assert "yolo11n.pt" not in [model.id for model in available_models()]


@pytest.mark.parametrize("task,suffix", [("detect", ""), ("segment", "-seg"), ("obb", "-obb"), ("classify", "-cls")])
@pytest.mark.parametrize("scale", list("nsmlx"))
def test_scratch_sizes_copy_shared_yaml_without_losing_scale(monkeypatch, tmp_path, task, suffix, scale):
    monkeypatch.delenv("WORKBENCH_TRAINING_WEIGHTS_DIR", raising=False)
    package = tmp_path / "ultralytics"
    configurations = package / "cfg/models/11"
    configurations.mkdir(parents=True)
    yaml = configurations / f"yolo11{suffix}.yaml"
    yaml.write_bytes(b"shared-scaled-architecture")
    monkeypatch.setattr("app.training.worker.find_spec", lambda _: SimpleNamespace(origin=str(package / "__init__.py")))
    identifier = f"yolo11{scale}{suffix}"
    option = resolve_model(identifier)
    assert option.task == task and not option.pretrained
    directory = tmp_path / "task"
    directory.mkdir()
    copied, _, pretrained = _copy_model(SimpleNamespace(config={"modelId": identifier}, snapshot=None), directory, lambda: None)
    assert copied.name == identifier + ".yaml"
    assert copied.read_bytes() == yaml.read_bytes()
    assert not pretrained
