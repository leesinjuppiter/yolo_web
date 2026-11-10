from datetime import datetime
from typing import Literal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

ReviewDecision = Literal["keep_both", "discard_image", "discard_related"]
StoredDecision = Literal["not_similar", "keep_both", "discard_first", "discard_second"]
ReviewPair = tuple[str, str, str, str]


def pair_key(image_id: str, related_id: str, image_sha: str, related_sha: str) -> ReviewPair:
    if image_id < related_id:
        return image_id, related_id, image_sha, related_sha
    return related_id, image_id, related_sha, image_sha


class DatasetSimilarityReview(Base):
    __tablename__ = "dataset_similarity_reviews"
    __table_args__ = (
        CheckConstraint("first_image_id < second_image_id", name="ck_dataset_similarity_reviews_pair_order"),
        CheckConstraint(
            "decision IN ('not_similar','keep_both','discard_first','discard_second')",
            name="ck_dataset_similarity_reviews_decision",
        ),
    )

    dataset_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True,
    )
    first_image_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("dataset_images.id", ondelete="CASCADE"), primary_key=True, index=True,
    )
    second_image_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("dataset_images.id", ondelete="CASCADE"), primary_key=True, index=True,
    )
    first_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    second_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    decision: Mapped[StoredDecision] = mapped_column(String(16))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
