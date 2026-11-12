"""File IO for immutable active-learning evidence."""
import json
from hashlib import sha256
from pathlib import Path

from app.core.config import data_dir
from app.core.storage import resolve_image
from app.training.repository import task_dir


def digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def directory(task_id: str) -> Path:
    return data_dir() / "active_learning" / task_id


def image_digest(image) -> str:
    return sha256(resolve_image(image.storage_path).read_bytes()).hexdigest()


def load_source(task) -> dict:
    from app.evaluation.snapshot import load_training_snapshot
    root, manifest, samples = load_training_snapshot(task)
    if not any(row["split"] == "val" for row in samples):
        raise ValueError("基线快照缺少固定 val 分集")
    for sample in samples:
        for kind in ("image", "label"):
            source_bytes({"taskId": task.id}, sample, kind)
    return {"taskId": task.id, "snapshotDigest": task.snapshot["digest"], "classes": manifest["classes"],
            "samples": samples, "taskType": task.config["task"]}


def source_bytes(source: dict, sample: dict, kind: str) -> bytes:
    root = (task_dir(source["taskId"]) / "input").resolve()
    path = (root / sample[kind + "_path"]).resolve()
    if not path.is_relative_to(root):
        raise ValueError("快照路径越界")
    content = path.read_bytes()
    if sha256(content).hexdigest() != sample[kind + "_sha256"]:
        raise ValueError("基线快照文件校验失败")
    return content
