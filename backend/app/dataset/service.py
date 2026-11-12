from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.annotation.validation import validate_annotations
from app.core import storage
from app.dataset import repository, schemas
from app.dataset.analysis.queue import REPORT_KINDS, invalidate_reports
from app.dataset.models import Dataset


def list_datasets(db: Session) -> list[schemas.DatasetResponse]:
    return [repository.serialize(dataset) for dataset in repository.list_datasets(db)]


def dataset_summary(db: Session, dataset_id: str) -> schemas.DatasetResponse:
    return repository.serialize(repository.get_dataset(db, dataset_id))


def create_dataset(db: Session, request: schemas.DatasetCreate) -> schemas.DatasetResponse:
    dataset = repository.create_dataset(db, request.name, request.task_type, request.keypoint_names)
    response = repository.serialize(dataset)
    db.commit()
    return response


def delete_dataset(db: Session, dataset_id: str) -> None:
    dataset = repository.get_dataset(db, dataset_id, lock=True, include_images=False)
    paths = [path for _, path in repository.list_image_files(db, dataset_id, include_excluded=True)]
    db.delete(dataset)
    db.commit()
    storage.remove_images(paths)


def upload_images(
    db: Session, dataset_id: str, split: schemas.Split | None, files: Iterable[tuple[str, bytes]],
) -> schemas.DatasetResponse:
    dataset = repository.get_dataset(db, dataset_id, lock=True)
    paths: list[str] = []
    try:
        for filename, data in files:
            name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
            if not name or len(name) > 255 or "\x00" in name:
                raise ValueError("图片文件名无效")
            stored = storage.save_image(data)
            paths.append(stored.path)
            image = repository.add_image(db, dataset.id, name, stored.width, stored.height, split, stored.path)
            dataset.images.append(image)
        if not paths:
            raise ValueError("请选择至少一张图片")
        db.flush()
        response = repository.serialize(dataset)
        invalidate_reports(db, dataset.id, REPORT_KINDS)
        db.commit()
    except Exception:
        db.rollback()
        storage.remove_images(paths)
        raise
    return response


def update_splits(
    db: Session, dataset_id: str, request: schemas.SplitUpdate,
) -> schemas.DatasetResponse:
    dataset = repository.get_dataset(db, dataset_id, lock=True)
    images = {image.id: image for image in dataset.images}
    if any(str(image_id) not in images for image_id in request.splits):
        raise repository.NotFound("选中的图片不属于当前数据集")
    changed = any(images[str(image_id)].split != split for image_id, split in request.splits.items())
    for image_id, split in request.splits.items():
        images[str(image_id)].split = split
    response = repository.serialize(dataset)
    if changed:
        invalidate_reports(db, dataset.id, ("validate",))
    db.commit()
    return response


def delete_image(db: Session, dataset_id: str, image_id: str) -> None:
    repository.get_dataset(db, dataset_id, lock=True)
    image = repository.get_image(db, dataset_id, image_id)
    path = image.storage_path
    db.delete(image)
    invalidate_reports(db, dataset_id, REPORT_KINDS)
    db.commit()
    storage.remove_images([path])


def exclude_image(db: Session, dataset_id: str, image_id: str) -> None:
    dataset = repository.get_dataset(db, dataset_id, lock=True, include_images=False)
    image = repository.get_image(db, dataset_id, image_id)
    image.excluded_at = datetime.now(timezone.utc)
    image.version += 1
    invalidate_reports(db, dataset_id, REPORT_KINDS)
    db.expire(dataset, ["images"])


def list_excluded_images(db: Session, dataset_id: str) -> list[schemas.ImageResponse]:
    dataset = repository.get_dataset(db, dataset_id, include_images=False)
    class_indices = {entry.id: entry.index for entry in dataset.classes}
    return [repository.serialize_image(image, class_indices) for image in repository.list_excluded_images(db, dataset_id)]


def restore_excluded_image(db: Session, dataset_id: str, image_id: str) -> schemas.ImageResponse:
    dataset = repository.get_dataset(db, dataset_id, lock=True, include_images=False)
    image = repository.get_image(db, dataset_id, image_id, include_excluded=True)
    if image.excluded_at is not None:
        image.excluded_at = None
        image.version += 1
        invalidate_reports(db, dataset_id, REPORT_KINDS)
    response = repository.serialize_image(image, {entry.id: entry.index for entry in dataset.classes})
    db.commit()
    return response


def update_class(
    db: Session, dataset_id: str, class_id: str, request: schemas.ClassUpdate,
) -> schemas.ClassResponse:
    dataset = repository.get_dataset(db, dataset_id, lock=True, include_images=False)
    entry = next((item for item in dataset.classes if item.id == class_id), None)
    if entry is None:
        raise repository.NotFound("该类别不属于当前数据集")
    if (entry.name, entry.color) != (request.previous.name, request.previous.color):
        raise repository.Conflict("该类别已被其他操作更新，请重新载入数据集")
    if any(item.id != class_id and item.name.casefold() == request.name.casefold() for item in dataset.classes):
        raise repository.Conflict(f"类别「{request.name}」已存在")
    renamed = entry.name != request.name
    entry.name, entry.color = request.name, request.color.lower()
    response = schemas.ClassResponse(id=entry.id, name=entry.name, color=entry.color, index=entry.index)
    if renamed:
        invalidate_reports(db, dataset_id, ("quality",))
    db.commit()
    return response


def _add_classes(
    db: Session, dataset: Dataset, classes: list[schemas.ClassInput],
) -> set[str]:
    names = {entry.name.casefold(): entry.id for entry in dataset.classes}
    existing = {entry.id: entry for entry in dataset.classes}
    seen = set()
    for value in classes:
        entry_id = str(value.id)
        if entry_id in seen:
            raise ValueError("类别 ID 不能重复")
        seen.add(entry_id)
        entry = existing.get(entry_id)
        if entry is not None:
            if entry.name != value.name or entry.color != value.color:
                raise repository.Conflict("已有类别信息发生变化，请重新载入数据集")
            continue
        key = value.name.casefold()
        if key in names:
            raise repository.Conflict(f"类别「{value.name}」已存在，请重新载入数据集")
        entry = repository.add_class(db, dataset.id, entry_id, value.name, value.color, len(existing))
        dataset.classes.append(entry)
        names[key] = entry_id
        existing[entry_id] = entry
    return set(existing)


def save_annotations(
    db: Session, dataset_id: str, image_id: str, request: schemas.AnnotationSave, *, compact: bool = False,
) -> schemas.DatasetResponse | schemas.AnnotationSaveResponse:
    dataset = repository.get_dataset(db, dataset_id, lock=True, include_images=False)
    image = repository.get_image(db, dataset_id, image_id)
    if image.version != request.version:
        raise repository.Conflict("图片标注已被其他操作更新，请重新载入")
    class_ids = _add_classes(db, dataset, request.classes)
    image.annotations = validate_annotations(
        task_type=dataset.task_type, width=image.width, height=image.height,
        keypoint_names=dataset.keypoint_names, class_ids=class_ids, status=request.status,
        annotations=request.annotations,
    )
    image.status = request.status
    image.version += 1
    if compact:
        classes = repository.serialize_classes(dataset)
        class_indices = {str(entry.id): entry.index for entry in classes}
        response = schemas.AnnotationSaveResponse(image=repository.serialize_image(image, class_indices), classes=classes)
    else:
        response = repository.serialize(dataset)
    invalidate_reports(db, dataset_id, ("validate", "quality"))
    db.commit()
    return response


def image_path(db: Session, dataset_id: str, image_id: str) -> Path:
    image = repository.get_image(db, dataset_id, image_id, include_excluded=True)
    path = storage.resolve_image(image.storage_path)
    if not path.is_file():
        raise repository.NotFound("图片文件不存在")
    return path


def image_thumbnail(db: Session, dataset_id: str, image_id: str) -> Path:
    from app.dataset.thumbnails import thumbnail_path

    return thumbnail_path(image_path(db, dataset_id, image_id))
