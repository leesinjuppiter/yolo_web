"""CPU-only isolated evaluation. No database access in this process."""
import json
import os
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
import sys


def run(job: dict) -> dict:
    from ultralytics import YOLO
    from app.training.runner import _values
    result = YOLO(job["modelPath"]).val(
        data=job["snapshot"]["dataPath"], split="test", device="cpu", workers=0,
        imgsz=job["imgsz"], batch=1, plots=False, save=False, conf=0.001, iou=0.7,
        project=job["directory"], name="validation", exist_ok=True, verbose=False)
    protocol = {"snapshotDigest": job["snapshot"]["digest"], "taskType": job["taskType"],
                "imgsz": job["imgsz"], "conf": 0.001, "iou": 0.7, "batch": 1,
                "evaluator": version("ultralytics"), "split": "test"}
    digest = sha256(json.dumps(protocol, sort_keys=True).encode()).hexdigest()
    return {"metrics": _values(result.results_dict), "snapshot": job["snapshot"],
            "protocol": protocol, "protocolDigest": digest, "actualDevice": "cpu",
            "modelSha256": job["modelSha256"], "qualityStatus": "not_assessed",
            "notice": "独立测试评估完成；未设定业务阈值，不代表生产合格",
            "perClass": [{"classIndex": int(index), "name": job["snapshot"]["classNames"][int(index)],
                          "map50_95": float(score)}
                         for index, score in zip(result.box.ap_class_index, result.box.maps[result.box.ap_class_index])]}


if __name__ == "__main__":
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    report = run(job)
    Path(job["directory"], "report.json").write_text(json.dumps(report, ensure_ascii=False, allow_nan=False), encoding="utf-8")
