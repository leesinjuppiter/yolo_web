"""Persist YOLO imports and write archives from saved dataset records."""

from collections.abc import Callable, Collection, Iterator
from functools import partial
from pathlib import Path, PurePosixPath
from tempfile import SpooledTemporaryFile
from typing import BinaryIO
from uuid import uuid4
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

import yaml
from sqlalchemy.orm import Session

from app.annotation.validation import validate_annotations
from app.core.config import data_dir
from app.core.storage import remove_images, resolve_image, save_image
from app.dataset import repository, schemas
from app.dataset.analysis.queue import REPORT_KINDS, invalidate_reports
from app.yolo import from_yolo, to_yolo

from .archive import (
    MAX_ARCHIVE_BYTES, MAX_IMAGE_BYTES, MAX_TEXT_BYTES, SPLITS, archive_reference, classification_index,
    detection_index, inspect_members, label_path, pose_schema, read_bytes, read_config,
)
from .local_directory import directory_members, directory_reference, directory_root, read_directory_file

CLASS_COLORS = ("#2589bd", "#7651ed", "#d18a12", "#358161", "#be5372")


def _dataset_index(files: Collection[PurePosixPath], text_at: Callable[[PurePosixPath], str], task_type: str,
                   reference: Callable[[PurePosixPath, str], PurePosixPath]):
    if task_type == "classify":
        names, entries = classification_index(files)
        return names, entries, [], 3
    root, config = read_config(files, text_at, required=True)
    names, entries = detection_index(files, root, config, text_at, reference)
    if task_type != "pose" and "kpt_shape" in config:
        raise ValueError("此归档包含姿态定义，请选择姿态任务")
    keypoints, dimensions = pose_schema(config, len(names)) if task_type == "pose" else ([], 3)
    return names, entries, keypoints, dimensions


def _labels(files: Collection[PurePosixPath], text_at: Callable[[PurePosixPath], str], path: PurePosixPath,
            class_name: str | None, class_indices: dict[str, int]) -> tuple[str, str]:
    if class_name is not None:
        return str(class_indices[class_name]), "annotated"
    label = label_path(path)
    if label not in files:
        return "", "unlabeled"
    labels = text_at(label)
    return labels, "annotated" if labels.strip() else "negative"


def _import_samples(
    db: Session, name: str, task_type: str, files: Collection[PurePosixPath],
    bytes_at: Callable[[PurePosixPath, int], bytes], reference: Callable[[PurePosixPath, str], PurePosixPath],
) -> schemas.DatasetResponse:
    def text_at(path: PurePosixPath) -> str:
        return bytes_at(path, MAX_TEXT_BYTES).decode("utf-8-sig")

    names, entries, keypoints, dimensions = _dataset_index(files, text_at, task_type, reference)
    if not entries:
        raise ValueError("数据集中没有符合布局的分集图片")
    request = schemas.DatasetCreate(name=name, task_type=task_type, keypoint_names=keypoints)
    saved_paths = []
    try:
        dataset = repository.create_dataset(db, request.name, request.task_type, request.keypoint_names)
        class_ids = [str(uuid4()) for _ in names]
        for index, (label, class_id) in enumerate(zip(names, class_ids)):
            repository.add_class(db, dataset.id, class_id, label, CLASS_COLORS[index % len(CLASS_COLORS)], index)
        class_id_set = set(class_ids)
        class_indices = {label: index for index, label in enumerate(names)}
        for count, (path, split, class_name) in enumerate(entries, 1):
            try:
                stored = save_image(bytes_at(path, MAX_IMAGE_BYTES))
                saved_paths.append(stored.path)
                labels, status = _labels(files, text_at, path, class_name, class_indices)
                annotations = from_yolo(labels, task_type, stored.width, stored.height, class_ids, keypoints, dimensions)
                validated = validate_annotations(task_type=task_type, width=stored.width, height=stored.height,
                                                 keypoint_names=keypoints, class_ids=class_id_set,
                                                 status=status, annotations=annotations)
                repository.add_image(db, dataset.id, path.name, stored.width, stored.height, split, stored.path,
                                     status=status, annotations=validated)
            except ValueError as exc:
                raise ValueError(f"{path}：{exc}") from exc
            if count % 500 == 0:
                db.flush()
        response = repository.serialize(dataset)
        invalidate_reports(db, dataset.id, REPORT_KINDS)
        db.commit()
        return response
    except Exception:
        db.rollback()
        remove_images(saved_paths)
        raise


def import_yolo(db: Session, source: BinaryIO, filename: str, task_type: str, *,
                name: str | None = None) -> schemas.DatasetResponse:
    if source.seek(0, 2) > MAX_ARCHIVE_BYTES:
        raise ValueError("ZIP 文件不能超过 256 MiB")
    source.seek(0)
    name = name or Path(filename.replace("\\", "/")).stem[:120] or "YOLO 数据集"
    try:
        with ZipFile(source) as archive:
            files = inspect_members(archive)

            def bytes_at(path: PurePosixPath, limit: int) -> bytes:
                return read_bytes(archive, files[path], limit)

            return _import_samples(db, name, task_type, files, bytes_at, archive_reference)
    except (BadZipFile, NotImplementedError, EOFError) as exc:
        raise ValueError("无法读取 ZIP 或不支持此压缩方式") from exc


def import_yolo_directory(db: Session, folder: str, task_type: str, *, name: str | None = None) -> schemas.DatasetResponse:
    root = directory_root(folder)
    return _import_samples(db, name or root.name[:120], task_type, directory_members(root),
                           partial(read_directory_file, root), partial(directory_reference, root))


def _portable_component(name: str) -> str:
    invalid = '<>:"/\\|?*'
    reserved = {"CON", "PRN", "AUX", "NUL", *[f"{kind}{number}" for kind in ("COM", "LPT") for number in range(1, 10)]}
    cleaned = "".join("_" if char in invalid or ord(char) < 32 else char for char in name).strip(" .")
    if not cleaned or cleaned.split(".")[0].upper() in reserved:
        return "_" + cleaned
    return cleaned


def _export_config(task_type: str, names: list[str], keypoint_names: list[str], splits: set[str]) -> dict:
    config = {"train": "images/train", "val": "images/val", "names": names}
    if "test" in splits:
        config["test"] = "images/test"
    if task_type == "pose":
        config["kpt_shape"] = [len(keypoint_names), 3]
        config["kpt_names"] = dict.fromkeys(range(len(names)), keypoint_names)
    return config


def _exportable(dataset, include_negative: bool):
    statuses = {"annotated", "negative"} if include_negative and dataset.task_type != "classify" else {"annotated"}
    images = [image for image in dataset.images if image.status in statuses]
    if not images:
        raise ValueError("没有符合导出条件的图片，请先保存标注或负样本状态")
    if any(image.split not in SPLITS for image in images):
        raise ValueError("存在未分配分集的可导出图片，请先保存分集")
    positive_splits = {image.split for image in images if image.status == "annotated"}
    missing = [split for split in ("train", "val") if split not in positive_splits]
    if missing:
        raise ValueError(f"导出前请在 {'、'.join(missing)} 分集各保存至少一张已标注图片")
    return images


def _write_archive(archive: ZipFile, dataset, images, include_images: bool) -> None:
    classes = sorted(dataset.classes, key=lambda item: item.index)
    class_indices = {item.id: index for index, item in enumerate(classes)}
    class_ids = set(class_indices)
    names = [item.name for item in classes]
    splits = {image.split for image in images}
    if not names:
        raise ValueError("导出前至少需要定义一个类别")
    is_classification = dataset.task_type == "classify"
    if is_classification:
        if not include_images:
            raise ValueError("分类数据集依赖按类别组织的图片，请启用打包原始图像")
        if any(_portable_component(name) != name for name in names) or len(set(map(str.casefold, names))) != len(names):
            raise ValueError("分类类别名称需要是有效且互不冲突的目录名")
        for split in sorted(splits):
            for name in names:
                archive.writestr(f"{split}/{name}/", "")
    else:
        config = _export_config(dataset.task_type, names, dataset.keypoint_names, splits)
        archive.writestr("data.yaml", yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
        for split in ("train", "val"):
            archive.writestr(f"images/{split}/", "")
            archive.writestr(f"labels/{split}/", "")

    for image in images:
        try:
            annotations = validate_annotations(
                task_type=dataset.task_type, width=image.width, height=image.height,
                keypoint_names=dataset.keypoint_names, class_ids=class_ids,
                status=image.status, annotations=image.annotations,
            )
            path = resolve_image(image.storage_path)
            if not path.is_file():
                raise ValueError("原图文件缺失")
            stem = _portable_component(Path(image.name.replace("\\", "/")).stem)[:100] + "-" + image.id
            filename = stem + path.suffix
            if is_classification:
                class_name = names[class_indices[annotations[0]["class_id"]]]
                archive.write(path, f"{image.split}/{class_name}/{filename}")
            else:
                labels = to_yolo(annotations, dataset.task_type, image.width, image.height,
                                 class_indices, dataset.keypoint_names)
                archive.writestr(f"labels/{image.split}/{stem}.txt", labels)
                if include_images:
                    archive.write(path, f"images/{image.split}/{filename}")
        except (IndexError, KeyError, OSError, ValueError) as exc:
            raise ValueError(f"{image.name}：{exc}") from exc


def export_yolo(db: Session, dataset_id: str, include_images: bool, include_negative: bool) -> BinaryIO:
    dataset = repository.get_dataset(db, dataset_id)
    images = _exportable(dataset, include_negative)
    folder = data_dir() / "exports"
    folder.mkdir(parents=True, exist_ok=True)
    output = SpooledTemporaryFile(max_size=16 * 1024 * 1024, dir=folder)
    try:
        with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
            _write_archive(archive, dataset, images, include_images)
        output.seek(0)
        return output
    except Exception:
        output.close()
        raise


def stream_archive(output: BinaryIO) -> Iterator[bytes]:
    with output:
        while chunk := output.read(256 * 1024):
            yield chunk
