from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.dataset.models import new_id


class Iteration(Base):
    __tablename__ = "active_learning_iterations"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    goal: Mapped[str] = mapped_column(String(2000), default="")
    dataset_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("datasets.id"))
    baseline_version_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("model_versions.id"))
    source_task_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("training_tasks.id"))
    task_type: Mapped[str] = mapped_column(String(12))
    source: Mapped[dict] = mapped_column(JSONB)
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RecommendationTask(Base):
    __tablename__ = "active_learning_tasks"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    iteration_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("active_learning_iterations.id"), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), unique=True)
    config: Mapped[dict] = mapped_column(JSONB)
    inputs: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(12), default="queued", index=True)
    phase: Mapped[str] = mapped_column(String(32), default="queued")
    processed: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    logs: Mapped[list] = mapped_column(JSONB, default=list)
    error: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Candidate(Base):
    __tablename__ = "active_learning_candidates"
    __table_args__ = (UniqueConstraint("iteration_id", "image_id", "purpose", name="uq_al_candidate_image"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    iteration_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("active_learning_iterations.id"), index=True)
    task_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("active_learning_tasks.id"), index=True)
    image_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    purpose: Mapped[str] = mapped_column(String(12))
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    review: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TrainingManifest(Base):
    __tablename__ = "active_learning_manifests"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    iteration_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("active_learning_iterations.id"), index=True)
    digest: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
