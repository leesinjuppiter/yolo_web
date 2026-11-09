from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.dataset import schemas
from app.dataset.models import Dataset, DatasetClass, DatasetImage


class NotFound(LookupError):
    pass


class Conflict(ValueError):
    pass


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


def get_dataset(db: Session, dataset_id: str, *, lock: bool = False) -> Dataset:
    if not lock:
        _start_read_snapshot(db)
    query = select(Dataset).where(Dataset.id == str(dataset_id)).options(
        selectinload(Dataset.classes), selectinload(Dataset.images),
    )
    if lock:
        query = query.with_for_update()
    dataset = db.scalar(query)
    if dataset is None:
        raise NotFound("未找到数据集")
    return dataset


def get_image(db: Session, dataset_id: str, image_id: str) -> DatasetImage:
    image = db.scalar(select(DatasetImage).where(
        DatasetImage.id == str(image_id),
        DatasetImage.dataset_id == str(dataset_id),
    ))
    if image is None:
        raise NotFound("未找到图片")
    return image


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


def serialize(dataset: Dataset) -> schemas.DatasetResponse:
    classes = [
        schemas.ClassResponse(id=entry.id, name=entry.name, color=entry.color, index=entry.index)
        for entry in dataset.classes
    ]
    class_indices = {str(entry.id): entry.index for entry in classes}
    images = [
        schemas.ImageResponse(
            id=image.id, name=image.name, width=image.width, height=image.height, split=image.split,
            status=image.status, version=image.version,
            url=f"/api/datasets/{dataset.id}/images/{image.id}/content",
            annotations=[
                {**annotation, "class_index": class_indices[annotation["class_id"]]}
                for annotation in image.annotations
            ],
        )
        for image in dataset.images
    ]
    return schemas.DatasetResponse(
        id=dataset.id, name=dataset.name, task_type=dataset.task_type, created_at=dataset.created_at,
        keypoint_names=dataset.keypoint_names, classes=classes, images=images,
    )
