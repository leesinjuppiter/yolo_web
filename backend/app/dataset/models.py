from datetime import datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def new_id() -> str:
    return str(uuid4())


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (
        CheckConstraint("task_type IN ('detect','segment','obb','pose','classify')", name="ck_datasets_task"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    task_type: Mapped[str] = mapped_column(String(12))
    keypoint_names: Mapped[list[str]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    classes: Mapped[list["DatasetClass"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="DatasetClass.index",
    )
    images: Mapped[list["DatasetImage"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="(DatasetImage.created_at, DatasetImage.id)",
    )


class DatasetClass(Base):
    __tablename__ = "dataset_classes"
    __table_args__ = (
        UniqueConstraint("dataset_id", "name", name="uq_dataset_classes_name"),
        UniqueConstraint("dataset_id", "index", name="uq_dataset_classes_index"),
        CheckConstraint('"index" >= 0', name="ck_dataset_classes_index"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("datasets.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    color: Mapped[str] = mapped_column(String(7))
    index: Mapped[int] = mapped_column(Integer)


class DatasetImage(Base):
    __tablename__ = "dataset_images"
    __table_args__ = (
        CheckConstraint("split IN ('train','val','test')", name="ck_dataset_images_split"),
        CheckConstraint("status IN ('unlabeled','negative','annotated')", name="ck_dataset_images_status"),
        CheckConstraint("width > 0 AND height > 0", name="ck_dataset_images_size"),
        CheckConstraint("version >= 0", name="ck_dataset_images_version"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    dataset_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("datasets.id", ondelete="CASCADE"), index=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    split: Mapped[str | None] = mapped_column(String(5))
    status: Mapped[str] = mapped_column(String(10))
    version: Mapped[int] = mapped_column(Integer, default=0)
    storage_path: Mapped[str] = mapped_column(String(160), unique=True)
    annotations: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
