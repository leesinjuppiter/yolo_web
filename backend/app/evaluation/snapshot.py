"""Freeze and verify the held-out test split of an existing training snapshot."""
import json
from hashlib import sha256
from pathlib import Path
import shutil

import yaml

from app.training.repository import task_dir


def _read_checked(root: Path, relative: str, digest: str) -> bytes:
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("评估快照文件路径越界")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("评估快照文件路径越界")
    value = path.read_bytes()
    if sha256(value).hexdigest() != digest:
        raise ValueError("评估快照文件校验失败")
    return value


def load_training_snapshot(task) -> tuple[Path, dict, list[dict]]:
    root = task_dir(task.id) / "input"
    manifest_bytes = (root / "manifest.json").read_bytes()
    if sha256(manifest_bytes).hexdigest() != (task.snapshot or {}).get("digest"):
        raise ValueError("训练快照清单已变化")
    manifest = json.loads(manifest_bytes)
    samples_bytes = _read_checked(root, manifest["samples_path"], manifest["samples_sha256"])
    samples = [json.loads(line) for line in samples_bytes.splitlines() if line]
    return root, manifest, samples


def prepare_snapshot(task, destination: Path, split: str = "test") -> dict:
    if split not in ("val", "test"):
        raise ValueError("评估仅允许 val/test 分集")
    root, manifest, samples = load_training_snapshot(task)
    selected = [row for row in samples if row["split"] == split]
    if not selected:
        raise ValueError(f"训练快照没有 {split} 分集")
    protected = ("train", "val") if split == "test" else ("train", "test")
    training_hashes = {row["image_sha256"] for row in samples if row["split"] in protected}
    if any(row["image_sha256"] in training_hashes for row in selected):
        raise ValueError(f"{split} 与其他分集存在完全重复图片，不能用于评估")
    classes = manifest["classes"]
    payload = {"classes": classes, "samples": selected, "split": split, "task": task.config["task"]}
    digest = sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    destination.mkdir(parents=True, exist_ok=False)
    try:
        for row in selected:
            for key in ("image", "label"):
                relative = row[key + "_path"]
                value = _read_checked(root, relative, row[key + "_sha256"])
                output = destination / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(value)
        (destination / "manifest.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        config = {"path": str(destination.resolve()), "test": f"images/{split}", "train": f"images/{split}",
                  "val": f"images/{split}", "names": [row["name"] for row in classes]}
        data = destination / "data.yaml"
        data.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    except Exception:
        shutil.rmtree(destination)
        raise
    return {"dataPath": str(data), "digest": digest, "sampleCount": len(selected),
            "classNames": config["names"], "split": split}


def prepare_test_snapshot(task, destination: Path) -> dict:
    return prepare_snapshot(task, destination, "test")


def validate_source(model_task, source_task, split: str) -> None:
    if model_task.config["task"] != source_task.config["task"]:
        raise ValueError("评估来源任务类型与模型不一致")
    _, source, samples = load_training_snapshot(source_task)
    _, model, model_samples = load_training_snapshot(model_task)
    names = lambda manifest: [row["name"] for row in manifest["classes"]]
    if names(source) != names(model):
        raise ValueError("评估来源类别或顺序与模型不一致")
    selected = [row for row in samples if row["split"] == split]
    if not selected:
        raise ValueError(f"模型来源训练快照没有 {split} 分集")
    used_splits = ("train", "val") if split == "test" else ("train",)
    used = {row["image_sha256"] for row in model_samples if row["split"] in used_splits}
    if any(row["image_sha256"] in used for row in selected):
        raise ValueError("评估图片与模型训练输入存在完全重复图片")
