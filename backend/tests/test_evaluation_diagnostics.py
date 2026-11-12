import json
from hashlib import sha256
from types import SimpleNamespace

import numpy as np
import pytest

from app.evaluation.diagnostics import diagnose, match_objects
from app.evaluation.evidence import read_evidence, write_evidence
from app.evaluation.schemas import EvaluationRequest
from app.evaluation.snapshot import prepare_snapshot, validate_source


def _write_snapshot(root):
    rows = []
    for split in ("train", "val", "test"):
        image, label = split.encode(), b"0 .5 .5 .2 .2"
        row = {"image_path": f"images/{split}/a.png", "label_path": f"labels/{split}/a.txt",
               "image_sha256": sha256(image).hexdigest(), "label_sha256": sha256(label).hexdigest(),
               "split": split}
        for kind, payload in (("image", image), ("label", label)):
            path = root / row[kind + "_path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        rows.append(row)
    contents = '\n'.join(json.dumps(row) for row in rows).encode()
    (root / "samples.jsonl").write_bytes(contents)
    manifest = json.dumps({"classes": [{"id": "coal", "name": "coal", "index": 0}],
                           "samples_path": "samples.jsonl", "samples_sha256": sha256(contents).hexdigest()}).encode()
    (root / "manifest.json").write_bytes(manifest)
    return {"digest": sha256(manifest).hexdigest()}


def test_matching_is_class_aware_and_one_to_one():
    overlap = np.array([[.9, .8, .95], [.1, .7, .2]])
    result = match_objects(overlap, [0, 0], [0, 0, 1], .5)
    # Ultralytics deduplicates predictions before GT; this is deliberately not Hungarian matching.
    assert result["summary"] == {"tp": 1, "fp": 2, "fn": 1}
    assert result["unmatchedPredictions"] == [1, 2]
    assert result["matches"] == [{"groundTruthIndex": 0, "predictionIndex": 0, "overlap": .9}]


@pytest.mark.parametrize("targets,predictions,counts", [([], [], (0, 0, 0)), ([0], [], (0, 0, 1)),
                                                       ([], [0], (0, 1, 0)), ([0], [1], (0, 1, 1))])
def test_empty_images_and_wrong_class(targets, predictions, counts):
    result = match_objects(np.ones((len(targets), len(predictions))), targets, predictions, .5)
    assert tuple(result["summary"].values()) == counts


def test_segment_uses_mask_not_box_quality():
    gt = [{"type": "polygon", "class_id": "coal", "polygon": [[0, 0], [9, 0], [9, 9], [0, 9]]}]
    prediction = [{"type": "bbox", "classIndex": 0, "bbox": {"x": 0, "y": 0, "width": 9, "height": 9}}]
    result = diagnose(gt, prediction, "segment", {"coal": 0}, .5, 10, 10, np.zeros((1, 10, 10), np.uint8))
    assert result["summary"] == {"tp": 0, "fp": 1, "fn": 1}
    assert result["box"]["summary"] == {"tp": 1, "fp": 0, "fn": 0}


def test_obb_equivalent_rotation_matches():
    box = {"cx": 30., "cy": 30., "width": 20., "height": 5., "angle": 0.}
    gt = [{"type": "obb", "class_id": "coal", "obb": box}]
    pred = [{"type": "obb", "classIndex": 0, "obb": {**box, "angle": 180.}}]
    assert diagnose(gt, pred, "obb", {"coal": 0}, .5, 60, 60)["summary"]["tp"] == 1


def test_diagnostic_freezes_val_and_does_not_copy_training(monkeypatch, tmp_path):
    task = SimpleNamespace(id="source", config={"task": "segment"})
    task.snapshot = _write_snapshot(tmp_path / "input")
    monkeypatch.setattr("app.evaluation.snapshot.task_dir", lambda _: tmp_path)
    prepared = prepare_snapshot(task, tmp_path / "frozen", "val")
    assert prepared["split"] == "val" and prepared["sampleCount"] == 1
    assert (tmp_path / "frozen/images/val/a.png").is_file()
    assert not (tmp_path / "frozen/images/train").exists()
    validate_source(task, task, "val")


def test_fixed_source_rejects_model_trained_on_evaluation_image(monkeypatch, tmp_path):
    source = SimpleNamespace(id="source", config={"task": "detect"})
    model = SimpleNamespace(id="model", config={"task": "detect"})
    for task in (source, model):
        task.snapshot = _write_snapshot(tmp_path / task.id / "input")
    root = tmp_path / "model" / "input"
    samples = [json.loads(line) for line in (root / "samples.jsonl").read_text().splitlines()]
    samples[0]["image_sha256"] = samples[1]["image_sha256"]
    contents = '\n'.join(json.dumps(item) for item in samples).encode()
    (root / "samples.jsonl").write_bytes(contents)
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["samples_sha256"] = sha256(contents).hexdigest()
    contents = json.dumps(manifest).encode()
    (root / "manifest.json").write_bytes(contents)
    model.snapshot["digest"] = sha256(contents).hexdigest()
    monkeypatch.setattr("app.evaluation.snapshot.task_dir", lambda task_id: tmp_path / task_id)
    with pytest.raises(ValueError, match="训练输入"):
        validate_source(model, source, "val")


def test_evidence_uses_image_index_not_client_path(tmp_path):
    write_evidence(tmp_path, 0, {"imageId": "../other", "summary": {"tp": 0}})
    assert read_evidence(tmp_path, "../other", [{"imageId": "../other"}])["summary"] == {"tp": 0}
    with pytest.raises(Exception, match="不存在"):
        read_evidence(tmp_path, "unknown", [{"imageId": "../other"}])


def test_old_request_keeps_final_test_default():
    value = EvaluationRequest(versionId="11111111-1111-1111-1111-111111111111")
    assert value.purpose == "final" and value.sourceTaskId is None


def test_runner_segment_report_keeps_mask_and_box_distinct(monkeypatch, tmp_path):
    import sys
    from app.evaluation import runner
    calls = []
    box = SimpleNamespace(ap_class_index=np.array([0]), maps=np.array([.8]), ap50=np.array([.9]),
                          p=np.array([.7]), r=np.array([.6]))
    mask = SimpleNamespace(ap_class_index=np.array([0]), maps=np.array([.4]), ap50=np.array([.5]),
                           p=np.array([.3]), r=np.array([.2]), mp=.3, mr=.2)
    result = SimpleNamespace(box=box, seg=mask, results_dict={"metrics/mAP50-95(B)": .8,
                                                           "metrics/mAP50-95(M)": .4})
    class Model:
        def val(self, **kwargs):
            calls.append(kwargs)
            return result
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=lambda _: Model()))
    monkeypatch.setattr(runner, "version", lambda _: "8.4.115")
    monkeypatch.setattr(runner, "_diagnostics", lambda model, job: [{"imageId": "one", "tp": 0, "fp": 1, "fn": 1}])
    report = runner.run({"modelPath": "fixed.pt", "modelSha256": "sha", "directory": str(tmp_path),
                         "taskType": "segment", "imgsz": 64, "purpose": "diagnostic", "sourceTaskId": "base",
                         "snapshot": {"dataPath": "fixed.yaml", "digest": "fixed", "classNames": ["coal"], "split": "val"}})
    assert calls[0]["split"] == "val" and calls[0]["device"] == "cpu"
    assert report["metrics"]["map50_95"] == .8 and report["metrics"]["maskMap50_95"] == .4
    assert report["metrics"]["maskPrecision"] == .3
    assert report["perClass"][0]["maskMap50_95"] == .4
    assert report["perImage"][0]["fn"] == 1
    assert report["protocol"]["overlap"] == "mask_iou"


def test_prediction_mask_holes_are_preserved_not_editable():
    import torch
    from app.evaluation.evidence import prediction_objects
    class Boxes:
        cls = torch.tensor([0])
        conf = torch.tensor([.8])
        xyxy = torch.tensor([[0., 0., 10., 10.]])
        def __len__(self):
            return 1
    mask = torch.ones((1, 10, 10))
    mask[:, 3:7, 3:7] = 0
    result = SimpleNamespace(boxes=Boxes(), masks=SimpleNamespace(data=mask), orig_shape=(10, 10))
    objects, raw_masks = prediction_objects(result, "segment")
    assert objects[0]["editable"] is False and len(objects[0]["contours"]) == 2
    assert raw_masks[0, 4, 4] == 0
