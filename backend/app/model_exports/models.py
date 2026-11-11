from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.dataset.models import new_id


class ExportTask(Base):
    __tablename__ = "model_export_tasks"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    version_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("model_versions.id"))
    idempotency_key: Mapped[str | None] = mapped_column(String(120), unique=True)
    config: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    phase: Mapped[str] = mapped_column(String(40), default="queued")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    report: Mapped[dict | None] = mapped_column(JSONB)
    logs: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
