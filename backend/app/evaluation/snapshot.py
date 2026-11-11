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


def prepare_test_snapshot(task, destination: Path) -> dict:
    root = task_dir(task.id) / "input"
    manifest_bytes = (root / "manifest.json").read_bytes()
    if sha256(manifest_bytes).hexdigest() != (task.snapshot or {}).get("digest"):
        raise ValueError("训练快照清单已变化")
    manifest = json.loads(manifest_bytes)
    samples_bytes = _read_checked(root, manifest["samples_path"], manifest["samples_sha256"])
    samples = [json.loads(line) for line in samples_bytes.splitlines() if line]
    test = [row for row in samples if row["split"] == "test"]
    if not test:
        raise ValueError("训练快照没有 test 分集，请使用包含独立测试集的训练结果")
    training_hashes = {row["image_sha256"] for row in samples if row["split"] in ("train", "val")}
    if any(row["image_sha256"] in training_hashes for row in test):
        raise ValueError("test 与 train/val 存在完全重复图片，不能作为独立评估")
    classes = manifest["classes"]
    payload = {"classes": classes, "samples": test, "split": "test", "task": task.config["task"]}
    digest = sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    destination.mkdir(parents=True, exist_ok=False)
    try:
        for row in test:
            for key in ("image", "label"):
                relative = row[key + "_path"]
                value = _read_checked(root, relative, row[key + "_sha256"])
                output = destination / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(value)
        (destination / "manifest.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        config = {"path": str(destination.resolve()), "test": "images/test", "train": "images/test",
                  "val": "images/test", "names": [row["name"] for row in classes]}
        data = destination / "data.yaml"
        data.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    except Exception:
        shutil.rmtree(destination)
        raise
    return {"dataPath": str(data), "digest": digest, "sampleCount": len(test),
            "classNames": config["names"], "split": "test"}
