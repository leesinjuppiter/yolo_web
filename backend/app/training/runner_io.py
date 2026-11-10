"""Training logs, observations, and files exposed to the workbench."""

import hashlib
import json
import re
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from PIL import Image

from app.training.runner_process import OutputTail


ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
ARTIFACTS = {
    "output/weights/best.pt": ("best", "best.pt", "checkpoint"),
    "output/weights/last.pt": ("last", "last.pt", "checkpoint"),
    "output/results.csv": ("metrics", "metrics.csv", "report"),
    "output/args.yaml": ("parameters", "args.yaml", "report"),
    "training.log": ("log", "training.log", "log"),
    "input/manifest.json": ("snapshot", "manifest.json", "report"),
    "input/samples.jsonl": ("samples", "samples.jsonl", "report"),
}
PREVIEWS = {
    "output/val_batch0_pred.jpg": ("preview-prediction", "val_batch0_pred.jpg", "preview"),
    "output/val_batch0_labels.jpg": ("preview-labels", "val_batch0_labels.jpg", "preview"),
}


def _jpeg(path: Path) -> bool:
    try:
        with Image.open(path) as image:
            image.load()
            return image.format == "JPEG"
    except (OSError, ValueError):
        return False


def _checkpoint(path: Path) -> bool:
    try:
        with ZipFile(path) as archive:
            names = archive.namelist()
            return any(name.endswith("/data.pkl") for name in names) and archive.testzip() is None
    except (BadZipFile, RuntimeError, OSError):
        return False


def artifact_manifest(directory: Path, *, check=lambda: None) -> list[dict]:
    artifacts = []
    files = ARTIFACTS | PREVIEWS if all(_jpeg(directory / path) for path in PREVIEWS) else ARTIFACTS
    for relative, (key, name, kind) in files.items():
        path = directory / relative
        if not path.is_file() or path.stat().st_size == 0:
            continue
        if kind == "checkpoint" and not _checkpoint(path):
            continue
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                check()
                digest.update(chunk)
        artifacts.append({"id": key, "name": name, "kind": kind, "path": relative,
                          "sha256": digest.hexdigest(), "sizeBytes": path.stat().st_size})
    return artifacts


def _log_level(message: str) -> str:
    lowered = message.lower()
    if "traceback (most recent call last)" in lowered or "error:" in lowered:
        return "error"
    if "warning" in lowered:
        return "warn"
    return "info"


class OutputCapture:
    def __init__(self, directory: Path):
        self.log_tail = OutputTail(directory / "training.log", progress_lines=True)
        self.event_tail = OutputTail(directory / "events.jsonl")
        self.log_sequence = 0
        self.metric_sequence = 0
        self.last_error: str | None = None
        self.failure: dict | None = None

    @property
    def complete(self) -> bool:
        return all(not tail.path.is_file() or tail.position == tail.path.stat().st_size
                   for tail in (self.log_tail, self.event_tail))

    def read(self, *, finished=False) -> tuple[list, list]:
        logs, events = [], []
        for line in self.log_tail.read(finished=finished):
            message = ANSI.sub("", line).replace("\x00", "")
            if not message:
                continue
            level = _log_level(message)
            if level == "error":
                self.last_error = message[:1000]
            self.log_sequence += 1
            logs.append((self.log_sequence, level, message[:4000]))
        for line in self.event_tail.read(finished=finished):
            try:
                event = json.loads(line)
            except ValueError:
                continue  # subprocess may have been terminated mid-write
            if event["kind"] == "failure":
                self.failure = event
            if event["kind"] == "metric":
                self.metric_sequence += 1
                values = event["values"]
                keys = ("boxLoss", "clsLoss", "segLoss", "map50", "map50_95", "maskMap50", "top1", "learningRate")
                summary = " | ".join(f"{key}={values[key]:.5g}" for key in keys if key in values)
                self.log_sequence += 1
                logs.append((self.log_sequence, "metric", f"Epoch {event['epoch']}" + (f" | {summary}" if summary else "")))
            events.append((self.metric_sequence, event))
        return logs, events


def failure_for(stage: str, exit_code: int, capture: OutputCapture) -> dict:
    code, summary, suggestion = "TRAINING_PROCESS_FAILED", "训练进程异常退出。", "查看训练日志末尾。"
    if capture.failure:
        code, summary = capture.failure["code"], capture.failure["summary"]
    elif capture.last_error:
        summary = capture.last_error
        error = summary.lower()
        if "out of memory" in error or "can't allocate memory" in error:
            code, suggestion = "CPU_MEMORY_EXHAUSTED", "尝试减小 Batch Size 或图像尺寸。"
        elif "modulenotfounderror" in error or "dll load failed" in error or "winerror 193" in error:
            code, suggestion = "DEPENDENCY_ERROR", "检查指定 Conda 环境中的训练依赖。"
    return {"code": code, "stage": stage, "summary": summary, "suggestion": suggestion, "exitCode": exit_code}
