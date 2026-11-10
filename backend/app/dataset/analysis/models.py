from datetime import datetime
from typing import Literal

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

ReportKind = Literal["validate", "duplicates", "quality"]
REPORT_KINDS: tuple[ReportKind, ...] = ("validate", "duplicates", "quality")


class DatasetAnalysisJob(Base):
    __tablename__ = "dataset_analysis_jobs"
    __table_args__ = (
        CheckConstraint("kind IN ('validate','duplicates','quality')", name="ck_dataset_analysis_jobs_kind"),
        CheckConstraint("status IN ('queued','running','ready','failed')", name="ck_dataset_analysis_jobs_status"),
        Index("ix_dataset_analysis_jobs_schedule", "status", "available_at"),
    )

    dataset_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[ReportKind] = mapped_column(String(12), primary_key=True)
    revision: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(10))
    priority: Mapped[int] = mapped_column(Integer)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer)
    claim_token: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed: Mapped[int | None] = mapped_column(Integer)
    total: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(200))


class DatasetReportSnapshot(Base):
    __tablename__ = "dataset_report_snapshots"
    __table_args__ = (
        CheckConstraint("kind IN ('validate','duplicates','quality')", name="ck_dataset_report_snapshots_kind"),
    )

    dataset_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[ReportKind] = mapped_column(String(12), primary_key=True)
    revision: Mapped[int] = mapped_column(BigInteger)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict] = mapped_column(JSONB)
