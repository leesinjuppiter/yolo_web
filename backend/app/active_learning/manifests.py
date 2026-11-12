"""Freeze reviewed inputs and materialize the exact training manifest."""
import json
from collections import Counter
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import yaml
from sqlalchemy import select

from app.active_learning import repository as repo, storage
from app.active_learning.models import Candidate, Iteration, TrainingManifest
from app.active_learning.review import assert_trainable
from app.dataset import repository as datasets
from app.dataset.models import DatasetImage
from app.training.snapshot import _sample_files


def _classes_match(iteration, dataset):
    old = [(entry["id"], entry["name"]) for entry in iteration.source["classes"]]
    if old != [(entry.id, entry.name) for entry in dataset.classes]:
        raise datasets.Conflict("类别定义与本轮基线不一致")


def _reviewed_inputs(db, iteration, dataset):
    selected = db.scalars(select(Candidate).where(Candidate.iteration_id == iteration.id,
        Candidate.selected.is_(True)).order_by(Candidate.id)).all()
    if not selected:
        raise datasets.Conflict("本轮尚未选择训练样本")
    result = []
    for row in selected:
        image = datasets.get_image(db, dataset.id, row.image_id)
        if not repo.review_valid(row, image, repo.class_values(dataset)):
            raise datasets.Conflict(f"{image.name} 尚未有效复核，请返回处理")
        sha = storage.image_digest(image)
        if sha != row.review["imageSha256"]:
            raise datasets.Conflict(f"{image.name} 原图内容已变化，请重新复核")
        assert_trainable(iteration, image, sha)
        result.append({"candidateId": row.id, "imageId": image.id, "version": image.version,
                       "imageSha256": sha, "review": row.review})
    return result


def _samples(db, iteration, inputs):
    originals = iteration.source["samples"]
    train = {row["image_id"]: {**row, "origin": "baseline"} for row in originals if row["split"] == "train"}
    classes = iteration.source["classes"]
    indices = {entry["id"]: entry["index"] for entry in classes}
    for item in inputs:
        image = db.get(DatasetImage, item["imageId"])
        clone = SimpleNamespace(**{key: getattr(image, key) for key in (
            "id", "name", "width", "height", "storage_path", "status", "annotations", "version")}, split="train")
        entry, _, _ = _sample_files(clone, iteration.task_type, indices, [row["name"] for row in classes])
        train[image.id] = {**entry, "origin": "reviewed", "candidateId": item["candidateId"]}
    seen, merged, excluded = {}, [], 0
    protected = {row["image_sha256"] for row in originals if row["split"] != "train"}
    for entry in train.values():
        sha = entry["image_sha256"]
        if sha in protected:
            raise datasets.Conflict(f"{entry['name']} 与固定 val/test 完全重复")
        if sha in seen:
            if seen[sha]["label_sha256"] != entry["label_sha256"]:
                raise datasets.Conflict(f"{entry['name']} 同内容图片有不同标注，请人工处理")
            excluded += 1
        else:
            seen[sha] = entry
            merged.append(entry)
    merged.extend({**row, "origin": "baseline"} for row in originals if row["split"] != "train")
    if not any(row["split"] == "train" and row["status"] == "annotated" for row in merged):
        raise ValueError("训练集至少需要一张已标注正样本")
    return merged, excluded


def _check_live_protection(db, iteration, samples):
    hashes = {row["image_sha256"] for row in samples if row["split"] == "train"}
    query = select(DatasetImage).where(DatasetImage.dataset_id == iteration.dataset_id,
        DatasetImage.excluded_at.is_(None), DatasetImage.split.in_(("val", "test")))
    for image in db.scalars(query):
        if storage.image_digest(image) in hashes:
            raise datasets.Conflict(f"{image.name} 当前已属于 val/test，不能混入本轮训练")


def prepare_training(db, iteration_id):
    with db.begin():
        iteration = repo.require_open(db, iteration_id)
        dataset = datasets.get_dataset(db, iteration.dataset_id, lock=True, include_images=False)
        _classes_match(iteration, dataset)
        inputs = _reviewed_inputs(db, iteration, dataset)
        samples, excluded = _samples(db, iteration, inputs)
        _check_live_protection(db, iteration, samples)
        # Check frozen source bytes now, not only when the worker eventually starts.
        for sample in iteration.source["samples"]:
            storage.source_bytes(iteration.source, sample, "image")
            storage.source_bytes(iteration.source, sample, "label")
        counts = repo.counts(db, iteration, dataset)
        counts.update(original=sum(row["split"] == "train" for row in iteration.source["samples"]),
                      total=sum(row["split"] == "train" for row in samples), excluded=excluded)
        payload = {"samples": samples, "inputs": inputs, "counts": counts,
                   "classDigest": storage.digest(repo.class_values(dataset))}
        row = TrainingManifest(iteration_id=iteration.id, payload=payload, digest=storage.digest(payload))
        db.add(row)
        db.flush()
        return {"ready": True, "iterationId": iteration.id, "manifestId": row.id, "manifestDigest": row.digest,
                "datasetId": iteration.dataset_id, "modelId": "version:" + iteration.baseline_version_id,
                "task": iteration.task_type, "counts": counts, "issues": [],
                "checks": [{"code": str(index), "label": name, "passed": True} for index, name in enumerate((
                    "人工复核", "版本一致", "任务与类别", "分集保护", "去重", "训练输入完整性"))]}


def validate_training_manifest(db, config):
    row = repo.get(db, TrainingManifest, str(config.manifestId))
    iteration = repo.get(db, Iteration, str(config.iterationId))
    if row.iteration_id != iteration.id or row.digest != config.manifestDigest:
        raise datasets.Conflict("本轮训练清单不匹配，请重新预检")
    if iteration.completed_at:
        raise datasets.Conflict("本轮已经完成，请创建下一轮")
    if (str(config.datasetId) != iteration.dataset_id or config.task != iteration.task_type
            or config.modelId != "version:" + iteration.baseline_version_id):
        raise ValueError("本轮训练必须使用固定的目标数据集、类型和基线模型")
    dataset = datasets.get_dataset(db, iteration.dataset_id, include_images=False)
    _classes_match(iteration, dataset)
    current = _reviewed_inputs(db, iteration, dataset)
    if storage.digest(current) != storage.digest(row.payload["inputs"]):
        raise datasets.Conflict("预检后选样或标注已变化，请重新预检")
    _check_live_protection(db, iteration, row.payload["samples"])
    return {"datasetName": dataset.name, "imageCount": len(row.payload["samples"]),
            "classCount": len(iteration.source["classes"]), "revision": row.digest, "errors": [], "warnings": [],
            "splitCounts": dict(Counter(item["split"] for item in row.payload["samples"]))}


def materialize_manifest(db, manifest_id: str, destination: Path, *, expected_digest=None, check_cancel=None):
    row = repo.get(db, TrainingManifest, manifest_id)
    if expected_digest != row.digest or storage.digest(row.payload) != row.digest:
        raise datasets.Conflict("训练清单摘要不一致")
    iteration = repo.get(db, Iteration, row.iteration_id)
    classes = iteration.source["classes"]
    destination.mkdir(parents=True, exist_ok=False)
    samples = []
    for entry in row.payload["samples"]:
        if check_cancel:
            check_cancel()
        _write_sample(db, iteration, entry, destination)
        samples.append({key: value for key, value in entry.items() if key not in ("origin", "candidateId")})
    samples_data = b"".join(json.dumps(item, ensure_ascii=False).encode() + b"\n" for item in samples)
    (destination / "samples.jsonl").write_bytes(samples_data)
    split_counts = dict(Counter(item["split"] for item in samples))
    data = {split: f"images/{split}" for split in split_counts}
    data["names"] = [entry["name"] for entry in classes]
    config = yaml.safe_dump(data, allow_unicode=True).encode()
    (destination / "data.yaml").write_bytes(config)
    metadata = {"dataset_id": iteration.dataset_id, "dataset_name": "主动学习固定输入",
                "task_type": iteration.task_type, "image_count": len(samples), "class_count": len(classes),
                "split_counts": split_counts, "revision": row.digest, "warnings": [], "format_version": 1,
                "classes": classes, "samples_path": "samples.jsonl", "samples_sha256": sha256(samples_data).hexdigest(),
                "data_path": "data.yaml", "data_sha256": sha256(config).hexdigest()}
    content = json.dumps(metadata, ensure_ascii=False).encode()
    (destination / "manifest.json").write_bytes(content)
    return {**metadata, "digest": sha256(content).hexdigest(), "data_path": str(destination / "data.yaml"),
            "manifest_path": str(destination / "manifest.json")}


def _write_sample(db, iteration, entry, destination):
    if entry["origin"] == "reviewed":
        image = db.get(DatasetImage, entry["image_id"])
        if image is None or image.excluded_at:
            raise datasets.Conflict("本轮图片已删除或排除，请重新预检")
        clone = SimpleNamespace(**{key: getattr(image, key) for key in (
            "id", "name", "width", "height", "storage_path")}, annotations=entry["annotations"],
            status=entry["status"], version=entry["version"], split="train")
        classes = iteration.source["classes"]
        _, image_bytes, labels = _sample_files(clone, iteration.task_type,
            {item["id"]: item["index"] for item in classes}, [item["name"] for item in classes])
        contents = {"image": image_bytes, "label": labels}
    else:
        contents = {kind: storage.source_bytes(iteration.source, entry, kind) for kind in ("image", "label")}
    for kind, content in contents.items():
        if sha256(content).hexdigest() != entry[kind + "_sha256"]:
            raise ValueError("准备期间训练文件发生变化")
        path = destination / entry[kind + "_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
