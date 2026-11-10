from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.dataset.models import new_id


class TrainingTask(Base):
    __tablename__ = "training_tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('created','queued','running','succeeded','failed','canceled')",
            name="ck_training_task_status",
        ),
        Index("ix_training_tasks_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), unique=True)
    dataset_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    dataset_name: Mapped[str] = mapped_column(String(120))
    dataset_image_count: Mapped[int] = mapped_column(Integer, default=0)
    dataset_class_count: Mapped[int] = mapped_column(Integer, default=0)
    dataset_revision: Mapped[str | None] = mapped_column(String(128))
    config: Mapped[dict] = mapped_column(JSONB)
    model_name: Mapped[str] = mapped_column(String(120))
    architecture: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(12), default="created")
    phase: Mapped[str] = mapped_column(String(40), default="checking")
    worker_token: Mapped[str | None] = mapped_column(String(36))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    snapshot: Mapped[dict | None] = mapped_column(JSONB)
    environment: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    epoch: Mapped[int] = mapped_column(Integer, default=0)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)
    failure: Mapped[dict | None] = mapped_column(JSONB)
    artifacts: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    previews: Mapped[list[dict]] = mapped_column(JSONB, default=list)


class TrainingLog(Base):
    __tablename__ = "training_logs"

    task_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("training_tasks.id", ondelete="CASCADE"), primary_key=True,
    )
    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    level: Mapped[str] = mapped_column(String(8))
    message: Mapped[str] = mapped_column(Text)


class TrainingMetric(Base):
    __tablename__ = "training_metrics"

    task_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("training_tasks.id", ondelete="CASCADE"), primary_key=True,
    )
    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    epoch: Mapped[int] = mapped_column(Integer)
    values: Mapped[dict] = mapped_column(JSONB)
    step: Mapped[int | None] = mapped_column(Integer)
    elapsed_seconds: Mapped[float | None]

