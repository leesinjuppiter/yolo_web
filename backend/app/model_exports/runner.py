"""CPU-only ONNX export in a disposable subprocess, with paired test evidence."""

import json
import os
import platform
import shutil
import sys
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

from app.model_exports.storage import digest, write_json


def _phase(value: str) -> None:
    print("WORKBENCH_PHASE=" + value, flush=True)


def _validation(model, data: Path, task: str, directory: Path, imgsz: int) -> dict:
    from app.training.runner import _values
    result = model.val(data=str(data), split="test", device="cpu", workers=0, batch=1,
                       imgsz=imgsz, rect=False, plots=False, save_json=False, project=str(directory),
                       name="validation", exist_ok=True, verbose=False)
    return {"metrics": _values(result.results_dict), "taskType": task,
            "metricScope": "rotated_box" if task == "obb" else "bounding_box"}


def numeric_check(source: Path, session, image: Path | None, imgsz: int, task: str) -> dict:
    import numpy as np
    import torch
    from PIL import Image
    from ultralytics import YOLO
    from ultralytics.data.augment import LetterBox
    sample = np.zeros((imgsz, imgsz, 3), dtype=np.uint8)
    if image:
        with Image.open(image) as opened:
            sample = np.asarray(opened.convert("RGB"))
    sample = LetterBox((imgsz, imgsz), auto=False)(image=sample)
    tensor = np.ascontiguousarray(sample.transpose(2, 0, 1)[None]).astype(np.float32)/255.0
    baseline = YOLO(str(source), task=task).model.cpu().float().eval()
    with torch.inference_mode():
        output = baseline(torch.from_numpy(tensor))
    while isinstance(output, (list, tuple)):
        output = output[0]
    actual = session.run(None, {session.get_inputs()[0].name: tensor})[0]
    expected = output.detach().cpu().numpy()
    if expected.shape != actual.shape or not np.isfinite(actual).all():
        raise ValueError("PT 与 ONNX 原始输出形状/有限性不一致")
    passed = bool(np.allclose(expected, actual, rtol=0.001, atol=0.001))
    result = {"status": "passed" if passed else "failed", "rtol": 0.001, "atol": 0.001,
              "maxAbsoluteError": float(np.max(np.abs(expected-actual))),
              "inputSampleSha256": digest(image) if image else None,
              "scope": "one fixed preprocessed image raw output; does not establish dataset accuracy"}
    if not passed:
        raise ValueError(f"PT/ONNX 原始输出数值检查失败，最大绝对误差 {result['maxAbsoluteError']:.6g}")
    return result


def benchmark(model, image: Path, imgsz: int, *, warmup: int = 3, iterations: int = 20) -> dict:
    import numpy as np
    from PIL import Image
    with Image.open(image) as opened:
        sample = np.array(opened.convert("RGB"))[:, :, ::-1].copy()
    for _ in range(warmup):
        model.predict(sample, imgsz=imgsz, rect=False, device="cpu", verbose=False)
    times = []
    for _ in range(iterations):
        start = perf_counter()
        model.predict(sample, imgsz=imgsz, rect=False, device="cpu", verbose=False)
        times.append((perf_counter()-start)*1000)
    elapsed = sum(times)
    return {"device": "cpu", "provider": "CPUExecutionProvider", "precision": "fp32",
            "inputSize": [1, 3, imgsz, imgsz], "batchSize": 1, "concurrency": 1,
            "warmup": warmup, "iterations": iterations, "samplesMs": times,
            "latencyAvgMs": float(np.mean(times)), "latencyP50Ms": float(np.percentile(times, 50)),
            "latencyP95Ms": float(np.percentile(times, 95)), "throughputImagesPerSecond": iterations*1000/elapsed,
            "timingScope": "in-memory BGR image → preprocess → CPU runtime → postprocess; excludes disk/network",
            "inputSampleSha256": digest(image), "memoryMeasurement": None,
            "limitations": "Shared server CPU test; other host processes and GPU training host load are not controlled"}


def run(config_path: Path) -> None:
    os.environ["YOLO_AUTOINSTALL"] = "false"
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    from ultralytics import YOLO, settings
    from ultralytics.data import utils
    import onnx
    import onnxruntime as ort
    import torch
    torch.set_num_threads(2)

    settings.update({key: False for key in ("sync", "wandb", "mlflow", "comet", "clearml") if key in settings})
    utils.check_font = lambda _name: None
    config = json.loads(config_path.read_text(encoding="utf-8"))
    directory = config_path.parent
    _phase("export")
    source = directory / "source.pt"
    model = YOLO(str(source), task=config["task"])
    if digest(source) != config["sourceSha256"]:
        raise ValueError("导出输入权重校验失败")
    names = model.names
    model_names = [names[index] for index in range(len(names))]
    if config["classNames"] and config["classNames"] != model_names:
        raise ValueError("模型类别顺序与训练快照不一致")
    config["classNames"] = model_names
    if model.task != config["task"]:
        raise ValueError("模型任务类型与注册版本不匹配")
    output = Path(model.export(format="onnx", device="cpu", half=False, int8=False,
                              dynamic=False, simplify=False, nms=False, batch=1, opset=17,
                              imgsz=config["imgsz"]))
    final = directory / "model.onnx"
    if output.resolve() != final.resolve():
        shutil.copyfile(output, final)
    _phase("load_check")
    onnx.checker.check_model(str(final))
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(final), sess_options=options, providers=["CPUExecutionProvider"])
    import numpy as np
    outputs = session.run(None, {session.get_inputs()[0].name: np.zeros((1, 3, config["imgsz"], config["imgsz"]), dtype=np.float32)})
    if not outputs or not all(np.isfinite(item).all() for item in outputs):
        raise ValueError("ONNX 加载或输出有限性检查失败")
    image = sorted((directory/"test-snapshot"/"images"/"test").iterdir())[0] if config.get("snapshot") else None
    numerical = numeric_check(source, session, image, config["imgsz"], config["task"])
    report = {"schemaVersion": 1, "format": "onnx", "precision": "fp32", "taskType": config["task"],
              "productionReady": False, "sourceSha256": config["sourceSha256"],
              "classNames": config["classNames"], "artifact": {"sha256": digest(final), "sizeBytes": final.stat().st_size},
              "input": {"shape": [1, 3, config["imgsz"], config["imgsz"]], "dtype": "float32", "dynamic": False},
              "pipeline": {"color": "RGB", "resize": "letterbox", "normalization": "divide_255",
                           "nmsEmbedded": False, "conf": 0.25, "iou": 0.7, "maxDet": 300},
              "environment": {"python": platform.python_version(), "system": platform.system(),
                              "machine": platform.machine(), "processor": platform.processor(),
                              "versions": {name: version(name) for name in ("ultralytics", "torch", "torchvision", "numpy", "onnx", "onnxruntime")}},
              "loadCheck": {"status": "passed", "providers": session.get_providers(),
                            "outputShapes": [list(item.shape) for item in outputs]},
              "numericCheck": numerical,
              "validation": {"status": "insufficient", "reason": config.get("snapshotError")},
              "benchmark": None}
    snapshot = config.get("snapshot")
    if snapshot:
        _phase("paired_validation")
        data = Path(snapshot["dataPath"])
        baseline = _validation(YOLO(str(source), task=config["task"]), data, config["task"], directory/"pt-evaluation", config["imgsz"])
        candidate = _validation(YOLO(str(final), task=config["task"]), data, config["task"], directory/"onnx-evaluation", config["imgsz"])
        delta = {key: candidate["metrics"][key]-value for key, value in baseline["metrics"].items() if key in candidate["metrics"]}
        report["validation"] = {"status": "completed", "qualityDecision": "threshold_not_configured",
                                "snapshotDigest": snapshot["digest"], "sampleCount": snapshot["sampleCount"],
                                "split": "test", "baseline": baseline, "candidate": candidate,
                                "delta": delta, "deltaUnit": "absolute fraction (multiply by 100 for percentage points)",
                                "protocol": {"rect": False, "batchSize": 1, "confidence": 0.001,
                                             "iou": 0.7, "maxDet": 300, "device": "cpu"},
                                "limitations": "Test-set metrics alone do not establish numeric equivalence or production accuracy"}
        _phase("benchmark")
        report["benchmark"] = benchmark(YOLO(str(final), task=config["task"]), image, config["imgsz"])
    write_json(directory/"report.json", report)
    from importlib.metadata import distributions
    lock = sorted(f"{item.metadata['Name']}=={item.version}" for item in distributions() if item.metadata.get("Name"))
    (directory/"environment-lock.txt").write_text("\n".join(lock)+"\n", encoding="utf-8")
    _phase("finished")


if __name__ == "__main__":
    if os.read(sys.stdin.fileno(), 1) != b"1":
        raise SystemExit(1)
    if os.name != "nt":
        from threading import Thread
        from app.training.runner import _watch_parent
        Thread(target=_watch_parent, daemon=True).start()
    run(Path(sys.argv[1]))
