"""CPU-only isolated evaluation. No database access in this process."""
import json
import os
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
import sys

from app.evaluation.diagnostics import diagnose
from app.evaluation.evidence import prediction_objects, read_samples, write_evidence


def _per_class(result, names: list[str], task: str) -> list[dict]:
    rows = []
    for position, index in enumerate(result.box.ap_class_index):
        row = {"classIndex": int(index), "name": names[int(index)],
               "map50_95": float(result.box.maps[int(index)]),
               "map50": float(result.box.ap50[position]),
               "precision": float(result.box.p[position]), "recall": float(result.box.r[position])}
        if task == "segment" and int(index) in result.seg.ap_class_index:
            offset = list(result.seg.ap_class_index).index(index)
            row.update(maskMap50_95=float(result.seg.maps[int(index)]), maskMap50=float(result.seg.ap50[offset]),
                       maskPrecision=float(result.seg.p[offset]), maskRecall=float(result.seg.r[offset]))
        rows.append(row)
    return rows


def _diagnostics(model, job: dict) -> list[dict]:
    directory = Path(job["directory"])
    manifest, samples = read_samples(directory)
    indices = {item["id"]: index for index, item in enumerate(manifest["classes"])}
    rows = []
    for ordinal, sample in enumerate(samples):
        image_id = sample.get("image_id", Path(sample["image_path"]).stem)
        prediction = model.predict(source=str(directory / "input" / sample["image_path"]),
                                   device="cpu", imgsz=job["imgsz"], conf=job.get("diagnosticConf", .25),
                                   iou=.7, max_det=300, retina_masks=True, verbose=False)[0]
        predictions, masks = prediction_objects(prediction, job["taskType"])
        height, width = prediction.orig_shape
        ground_truth = sample.get("annotations")
        if ground_truth is None:
            raise ValueError("此历史快照缺少原始标注，无法生成逐对象诊断，请重新生成训练快照")
        matching = diagnose(ground_truth, predictions, job["taskType"], indices,
                            job.get("diagnosticIou", .5), width, height, masks)
        evidence = {"imageId": image_id, "imageSha256": sample["image_sha256"],
                    "annotationVersion": sample.get("version"), "width": width, "height": height,
                    "groundTruth": ground_truth, "predictions": predictions, **matching}
        write_evidence(directory, ordinal, evidence, masks)
        row = {"imageId": image_id, "name": sample.get("name", image_id), **matching["summary"]}
        if "box" in matching:
            row["box"] = matching["box"]["summary"]
        rows.append(row)
    return rows


def run(job: dict) -> dict:
    from ultralytics import YOLO
    from app.training.runner import _values
    model = YOLO(job["modelPath"])
    split = job["snapshot"].get("split", "test")
    result = model.val(
        data=job["snapshot"]["dataPath"], split=split, device="cpu", workers=0,
        imgsz=job["imgsz"], batch=1, plots=False, save=False, conf=0.001, iou=0.7,
        project=job["directory"], name="validation", exist_ok=True, verbose=False)
    protocol = {"snapshotDigest": job["snapshot"]["digest"], "taskType": job["taskType"],
                "imgsz": job["imgsz"], "conf": 0.001, "iou": 0.7, "batch": 1,
                "evaluator": version("ultralytics"), "split": split, "maxDet": 300,
                "overlap": {"detect": "box_iou", "segment": "mask_iou", "obb": "prob_iou"}[job["taskType"]],
                "metricThresholds": [.5, .55, .6, .65, .7, .75, .8, .85, .9, .95]}
    digest = sha256(json.dumps(protocol, sort_keys=True).encode()).hexdigest()
    metrics = _values(result.results_dict)
    if job["taskType"] == "segment":
        metrics.update(maskPrecision=float(result.seg.mp), maskRecall=float(result.seg.mr))
    return {"metrics": metrics, "snapshot": job["snapshot"],
            "protocol": protocol, "protocolDigest": digest, "actualDevice": "cpu",
            "modelSha256": job["modelSha256"], "qualityStatus": "not_assessed",
            "purpose": job.get("purpose", "final"), "sourceTaskId": job.get("sourceTaskId"),
            "notice": "固定 val 诊断完成；结果用于日常迭代，不代表独立最终测试" if split == "val" else
                      "独立测试评估完成；未设定业务阈值，不代表生产合格",
            "perClass": _per_class(result, job["snapshot"]["classNames"], job["taskType"]),
            "perImage": _diagnostics(model, job) if job.get("purpose") == "diagnostic" else [],
            "diagnosticProtocol": {"conf": job.get("diagnosticConf", .25),
                                   "matchThreshold": job.get("diagnosticIou", .5), "overlap": protocol["overlap"],
                                   "nmsIou": .7, "maxDet": 300, "maskRaster": "original_image",
                                   "matching": "ultralytics_greedy_class_aware"}}


if __name__ == "__main__":
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    report = run(job)
    Path(job["directory"], "report.json").write_text(json.dumps(report, ensure_ascii=False, allow_nan=False), encoding="utf-8")
