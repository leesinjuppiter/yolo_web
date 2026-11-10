"""Prepare stable, task-local YOLO inputs without modifying the live dataset."""

import json
import os
from collections import Counter
from collections.abc import Callable
from hashlib import file_digest, sha256
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.annotation.validation import validate_annotations
from app.core.storage import MAX_IMAGE_BYTES, open_checked_image, resolve_image
from app.dataset import repository
from app.dataset.exchange.service import _portable_component
from app.dataset.models import Dataset, DatasetImage
from app.dataset.schemas import TASK_ANNOTATION
from app.yolo.conversion import to_yolo


_TASKS = TASK_ANNOTATION.keys() - {"pose"}
_SPLITS = ("train", "val", "test")
_BATCH_SIZE = 256
_FORMAT_VERSION = 1


class SnapshotError(ValueError):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def _issue(code: str, message: str, **details) -> dict:
    return {"code": code, "message": message, **details}


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _source_classes(dataset: Dataset) -> list[dict]:
    return [{"id": item.id, "name": item.name, "source_index": item.index} for item in dataset.classes]


def _metadata(db: Session, dataset: Dataset, classes: list[dict]) -> tuple[str, Counter]:
    """Compute a submission revision from a bounded stream of lightweight rows."""
    revision = sha256(_json_bytes([dataset.id, dataset.name, dataset.task_type, classes]))
    query = select(
        DatasetImage.id, DatasetImage.version, DatasetImage.status, DatasetImage.split,
        DatasetImage.name, DatasetImage.width, DatasetImage.height, DatasetImage.storage_path,
    ).where(DatasetImage.dataset_id == dataset.id, DatasetImage.excluded_at.is_(None))
    counts = Counter()
    with db.execute(query.order_by(DatasetImage.id).execution_options(yield_per=_BATCH_SIZE)) as result:
        for row in result:
            revision.update(_json_bytes(tuple(row)))
            counts[row.status, row.split] += 1
    return revision.hexdigest(), counts


def _eligible(status: str, task_type: str) -> bool:
    return status == "annotated" or (status == "negative" and task_type != "classify")


def _inspect(db: Session, dataset: Dataset, task_type: str, classes: list[dict]) -> dict:
    errors, warnings = [], []
    if task_type not in _TASKS:
        errors.append(_issue("TASK_TYPE_UNSUPPORTED", "此任务类型不支持训练"))
    elif dataset.task_type != task_type:
        errors.append(_issue("DATASET_TASK_MISMATCH", "训练任务类型与数据集类型不一致"))
    if not classes:
        errors.append(_issue("CLASSES_MISSING", "请先定义数据集类别"))
    names = [item["name"] for item in classes]
    if (len({name.casefold() for name in names}) != len(names)
            or task_type == "classify" and any(_portable_component(name) != name for name in names)):
        errors.append(_issue("CLASSES_INVALID", "类别名称重复或不能用于分类目录"))
    revision, counts = _metadata(db, dataset, classes)
    split_counts = dict.fromkeys(_SPLITS, 0)
    unassigned = skipped = 0
    for (status, split), count in counts.items():
        if not _eligible(status, task_type):
            skipped += count
        elif split in split_counts:
            split_counts[split] += count
        else:
            unassigned += count
    if unassigned:
        errors.append(_issue("SPLIT_UNASSIGNED", f"有 {unassigned} 张可用图片未分配分集", count=unassigned))
    for split in ("train", "val"):
        if counts["annotated", split] == 0:
            errors.append(_issue("SPLIT_NO_POSITIVE", f"{split} 分集至少需要一张已标注图片", split=split))
    if skipped:
        warnings.append(_issue("SAMPLES_SKIPPED", f"有 {skipped} 张未标注或不适用的图片不会纳入快照", count=skipped))
    return {
        "datasetName": dataset.name, "imageCount": sum(split_counts.values()), "classCount": len(classes),
        "splitCounts": split_counts, "revision": revision, "errors": errors, "warnings": warnings,
    }


def inspect_dataset(db: Session, dataset_id: str, task_type: str) -> dict:
    """Fast preflight. The worker rechecks geometry, file integrity, and leakage."""
    try:
        dataset = repository.get_dataset(db, dataset_id, include_images=False)
    except repository.NotFound:
        return {
            "datasetName": None, "imageCount": 0, "classCount": 0, "splitCounts": dict.fromkeys(_SPLITS, 0),
            "revision": None, "errors": [_issue("DATASET_NOT_FOUND", "未找到数据集")], "warnings": [],
        }
    return _inspect(db, dataset, task_type, _source_classes(dataset))


def _read_source(sample: DatasetImage) -> tuple[str, bytes]:
    source = resolve_image(sample.storage_path)
    with source.open("rb") as stream:
        before = os.fstat(stream.fileno())
        data = stream.read(MAX_IMAGE_BYTES + 1)
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("读取期间原图发生变化")
    with open_checked_image(data) as image:
        if image.size != (sample.width, sample.height):
            raise ValueError("原图尺寸与标注记录不一致")
        if min(image.size) < 10:
            raise ValueError("训练图片宽高至少需要 10 像素")
        if image.format == "JPEG" and not data.endswith(b"\xff\xd9"):
            raise ValueError("JPEG 缺少结束标记，请修复或重新导入")
    return source.suffix.lower(), data


def _sample_files(sample: DatasetImage, task_type: str, indices: dict[str, int], names: list[str]) -> tuple[dict, bytes, bytes | None]:
    try:
        annotations = validate_annotations(
            task_type=task_type, width=sample.width, height=sample.height, keypoint_names=[],
            class_ids=indices.keys(), status=sample.status, annotations=sample.annotations,
        )
        suffix, image_bytes = _read_source(sample)
        filename = sample.id + suffix
        entry = {
            "image_id": sample.id, "name": sample.name, "width": sample.width, "height": sample.height,
            "split": sample.split, "status": sample.status, "version": sample.version,
            "annotations": annotations, "image_sha256": sha256(image_bytes).hexdigest(),
        }
        if task_type == "classify":
            index = indices[annotations[0]["class_id"]]
            entry["image_path"] = f"{sample.split}/{names[index]}/{filename}"
            return entry, image_bytes, None
        labels = to_yolo(annotations, task_type, sample.width, sample.height, indices).encode("utf-8")
        entry.update(image_path=f"images/{sample.split}/{filename}", label_path=f"labels/{sample.split}/{sample.id}.txt",
                     label_sha256=sha256(labels).hexdigest())
        return entry, image_bytes, labels
    except (OSError, ValueError, TypeError) as exc:
        reason = "原图文件缺失或无法读取" if isinstance(exc, OSError) else str(exc)
        raise SnapshotError("SAMPLE_INVALID", f"{sample.name}：{reason}", {"imageId": sample.id}) from exc


def _layout(folder: Path, task_type: str, names: list[str], splits: list[str]) -> dict:
    if task_type == "classify":
        for split in splits:
            for name in names:
                (folder / split / name).mkdir(parents=True)
        return {"data_path": "."}
    config = {split: f"images/{split}" for split in splits}
    config["names"] = names
    data = yaml.safe_dump(config, allow_unicode=True, sort_keys=False).encode("utf-8")
    (folder / "data.yaml").write_bytes(data)
    for split in splits:
        (folder / "images" / split).mkdir(parents=True)
        (folder / "labels" / split).mkdir(parents=True)
    return {"data_path": "data.yaml", "data_sha256": sha256(data).hexdigest()}


def _check_leak(entry: dict, seen: dict[tuple[str, str], str]) -> None:
    split = entry["split"]
    if split not in ("train", "val"):
        return
    digest = entry["image_sha256"]
    other = "val" if split == "train" else "train"
    if related_id := seen.get((digest, other)):
        raise SnapshotError(
            "SPLIT_DATA_LEAK", f"train 和 val 含完全重复的图片（{entry['name']}），请调整分集后重试",
            {"imageId": entry["image_id"], "relatedImageId": related_id},
        )
    seen[digest, split] = entry["image_id"]


def _write_samples(db: Session, dataset_id: str, task_type: str, folder: Path, names: list[str], indices: dict[str, int],
                   check_cancel: Callable[[], None] | None) -> str:
    statuses = ("annotated",) if task_type == "classify" else ("annotated", "negative")
    query = select(DatasetImage).where(
        DatasetImage.dataset_id == dataset_id, DatasetImage.excluded_at.is_(None), DatasetImage.status.in_(statuses),
    ).order_by(DatasetImage.id).execution_options(yield_per=_BATCH_SIZE)
    seen: dict[tuple[str, str], str] = {}
    path = folder / "samples.jsonl"
    with db.scalars(query) as rows, path.open("wb") as manifest:
        for sample in rows:
            if check_cancel is not None:
                check_cancel()
            entry, image, labels = _sample_files(sample, task_type, indices, names)
            _check_leak(entry, seen)
            (folder / entry["image_path"]).write_bytes(image)
            if labels is not None:
                (folder / entry["label_path"]).write_bytes(labels)
            manifest.write(_json_bytes(entry) + b"\n")
    with path.open("rb") as manifest:
        return file_digest(manifest, "sha256").hexdigest()


def prepare_snapshot(db: Session, dataset_id: str, task_type: str, destination: Path, *,
                     expected_revision: str | None = None, check_cancel: Callable[[], None] | None = None) -> dict:
    """Publish an independent snapshot atomically using a fresh Session's consistent read."""
    if db.in_transaction():
        raise RuntimeError("构建训练快照需要独立的数据库会话")
    if check_cancel is not None:
        check_cancel()
    db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
    try:
        dataset = repository.get_dataset(db, dataset_id, include_images=False)
    except repository.NotFound as exc:
        raise SnapshotError("DATASET_NOT_FOUND", "训练快照准备前数据集已被删除") from exc
    classes = _source_classes(dataset)
    report = _inspect(db, dataset, task_type, classes)
    if expected_revision is not None and report["revision"] != expected_revision:
        raise SnapshotError("DATASET_CHANGED", "数据集在提交训练后发生变化，请检查后重新提交")
    if report["errors"]:
        first = report["errors"][0]
        raise SnapshotError(first["code"], first["message"], {"issues": report["errors"]})
    if task_type == "classify":
        # ImageFolder enumerates directory names lexicographically, independent of the business index.
        classes.sort(key=lambda item: item["name"])
    for index, entry in enumerate(classes):
        entry["index"] = index
    names = [item["name"] for item in classes]
    indices = {item["id"]: item["index"] for item in classes}
    splits = [split for split, count in report["splitCounts"].items() if count]
    destination = destination.resolve()
    if destination.exists():
        raise SnapshotError("SNAPSHOT_EXISTS", "此任务的训练快照已存在")
    meta = {"dataset_id": dataset.id, "dataset_name": dataset.name, "task_type": task_type,
            "image_count": report["imageCount"], "class_count": report["classCount"],
            "split_counts": report["splitCounts"], "revision": report["revision"], "warnings": report["warnings"]}
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".snapshot-", dir=destination.parent) as scratch:
            folder = Path(scratch) / "input"
            folder.mkdir()
            layout = _layout(folder, task_type, names, splits)
            samples_digest = _write_samples(db, dataset.id, task_type, folder, names, indices, check_cancel)
            if check_cancel is not None:
                check_cancel()
            payload = _json_bytes({**meta, **layout, "format_version": _FORMAT_VERSION, "classes": classes,
                                   "samples_path": "samples.jsonl", "samples_sha256": samples_digest})
            (folder / "manifest.json").write_bytes(payload)
            folder.rename(destination)
    except OSError as exc:
        raise SnapshotError("SNAPSHOT_IO", "无法写入训练快照，请检查磁盘空间和数据目录权限") from exc
    return {**meta, "digest": sha256(payload).hexdigest(), "data_path": str(destination / layout["data_path"]),
            "manifest_path": str(destination / "manifest.json")}
