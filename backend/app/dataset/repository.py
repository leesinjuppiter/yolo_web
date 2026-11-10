from collections import Counter
from collections.abc import Sequence
from typing import NamedTuple

from sqlalchemy import column, func, select, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session, selectinload

from app.dataset import schemas
from app.dataset.models import Dataset, DatasetClass, DatasetImage


class NotFound(LookupError):
    pass


class Conflict(ValueError):
    pass


class ImageSource(NamedTuple):
    id: str
    name: str
    storage_path: str


def _start_read_snapshot(db: Session) -> None:
    # Select-in loading reads classes and images separately. Both must see the same commit.
    if not db.in_transaction():
        db.connection(execution_options={"isolation_level": "REPEATABLE READ"})


def list_datasets(db: Session) -> Sequence[Dataset]:
    _start_read_snapshot(db)
    query = (
        select(Dataset)
        .options(selectinload(Dataset.classes), selectinload(Dataset.images))
        .order_by(Dataset.created_at.desc(), Dataset.id)
    )
    return db.scalars(query).all()


def get_dataset(db: Session, dataset_id: str, *, lock: bool = False, include_images: bool = True) -> Dataset:
    if not lock:
        _start_read_snapshot(db)
    query = select(Dataset).where(Dataset.id == str(dataset_id)).options(selectinload(Dataset.classes))
    if include_images:
        query = query.options(selectinload(Dataset.images))
    if lock:
        query = query.with_for_update()
    dataset = db.scalar(query)
    if dataset is None:
        raise NotFound("未找到数据集")
    return dataset


def get_image(db: Session, dataset_id: str, image_id: str, *, include_excluded: bool = False) -> DatasetImage:
    query = select(DatasetImage).where(
        DatasetImage.id == str(image_id),
        DatasetImage.dataset_id == str(dataset_id),
    )
    if not include_excluded:
        query = query.where(DatasetImage.excluded_at.is_(None))
    image = db.scalar(query)
    if image is None:
        raise NotFound("未找到图片")
    return image


def list_excluded_images(db: Session, dataset_id: str) -> Sequence[DatasetImage]:
    query = select(DatasetImage).where(
        DatasetImage.dataset_id == dataset_id, DatasetImage.excluded_at.is_not(None),
    ).order_by(DatasetImage.excluded_at.desc(), DatasetImage.id)
    return db.scalars(query).all()


def list_image_files(db: Session, dataset_id: str, *, include_excluded: bool = False) -> Sequence[tuple[str, str]]:
    query = select(DatasetImage.name, DatasetImage.storage_path).where(DatasetImage.dataset_id == dataset_id)
    if not include_excluded:
        query = query.where(DatasetImage.excluded_at.is_(None))
    return db.execute(query.order_by(DatasetImage.created_at, DatasetImage.id)).tuples().all()


def list_image_sources(db: Session, dataset_id: str) -> list[ImageSource]:
    sources = db.execute(
        select(DatasetImage.id, DatasetImage.name, DatasetImage.storage_path)
        .where(DatasetImage.dataset_id == dataset_id, DatasetImage.excluded_at.is_(None))
        .order_by(DatasetImage.created_at, DatasetImage.id)
    )
    return [ImageSource(*source) for source in sources]


def quality_counts(db: Session, dataset_id: str) -> tuple[Counter[str], Counter[str]]:
    dataset_filter = (DatasetImage.dataset_id == dataset_id, DatasetImage.excluded_at.is_(None))
    statuses = db.execute(
        select(DatasetImage.status, func.count()).where(*dataset_filter).group_by(DatasetImage.status)
    ).all()
    annotations = func.jsonb_array_elements(DatasetImage.annotations).table_valued(column("value", JSONB))
    class_id = annotations.c.value["class_id"].astext
    classes = db.execute(
        select(class_id, func.count()).select_from(DatasetImage).join(annotations, true())
        .where(*dataset_filter).group_by(class_id)
    ).all()
    return Counter(dict(statuses)), Counter(dict(classes))


def create_dataset(
    db: Session,
    name: str,
    task_type: str,
    keypoint_names: list[str] | None = None,
) -> Dataset:
    values = schemas.DatasetCreate(name=name, task_type=task_type, keypoint_names=keypoint_names or [])
    dataset = Dataset(**values.model_dump())
    db.add(dataset)
    db.flush()
    return dataset


def add_class(
    db: Session, dataset_id: str, id: str, name: str, color: str, index: int,
) -> DatasetClass:
    values = schemas.ClassInput(id=id, name=name, color=color)
    entry = DatasetClass(dataset_id=str(dataset_id), index=index, **values.model_dump(mode="json"))
    db.add(entry)
    return entry


def add_image(
    db: Session,
    dataset_id: str,
    name: str,
    width: int,
    height: int,
    split: str | None,
    storage_path: str,
    status: str = "unlabeled",
    annotations: list[dict] | None = None,
) -> DatasetImage:
    image = DatasetImage(
        dataset_id=str(dataset_id), name=name, width=width, height=height, split=split,
        storage_path=storage_path, status=status, annotations=annotations or [],
    )
    db.add(image)
    return image


def serialize_classes(dataset: Dataset) -> list[schemas.ClassResponse]:
    return [
        schemas.ClassResponse(id=entry.id, name=entry.name, color=entry.color, index=entry.index)
        for entry in dataset.classes
    ]


def serialize_image(image: DatasetImage, class_indices: dict[str, int]) -> schemas.ImageResponse:
    return schemas.ImageResponse(
        id=image.id, name=image.name, width=image.width, height=image.height, split=image.split,
        status=image.status, version=image.version, excluded_at=image.excluded_at,
        url=f"/api/datasets/{image.dataset_id}/images/{image.id}/content",
        annotations=[
            {**annotation, "class_index": class_indices[annotation["class_id"]]}
            for annotation in image.annotations
        ],
    )


def serialize(dataset: Dataset) -> schemas.DatasetResponse:
    classes = serialize_classes(dataset)
    class_indices = {str(entry.id): entry.index for entry in classes}
    return schemas.DatasetResponse(
        id=dataset.id, name=dataset.name, task_type=dataset.task_type, created_at=dataset.created_at,
        keypoint_names=dataset.keypoint_names, classes=classes,
        images=[serialize_image(image, class_indices) for image in dataset.images],
    )
