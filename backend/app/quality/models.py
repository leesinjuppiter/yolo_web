from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DatasetImageAnalysis(Base):
    __tablename__ = "dataset_image_analysis"

    image_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("dataset_images.id", ondelete="CASCADE"), primary_key=True,
    )
    file_signature: Mapped[list[int] | None] = mapped_column(JSONB(none_as_null=True))
    rule_version: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64))
    dhash: Mapped[str | None] = mapped_column(String(16))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
