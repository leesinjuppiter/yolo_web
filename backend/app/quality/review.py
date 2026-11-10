from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.dataset import repository, service
from app.dataset.analysis.models import DatasetReportSnapshot
from app.dataset.analysis.queue import invalidate_reports
from app.quality.fingerprints import signature_matches
from app.quality.models import DatasetImageAnalysis
from app.quality.review_models import DatasetSimilarityReview, ReviewDecision, ReviewPair, StoredDecision, pair_key


def load_review_decisions(db: Session, dataset_id: str) -> dict[ReviewPair, StoredDecision]:
    review = DatasetSimilarityReview
    rows = db.execute(
        select(review.first_image_id, review.second_image_id, review.first_sha256, review.second_sha256, review.decision)
        .where(review.dataset_id == dataset_id, review.decision == "keep_both", review.first_sha256 == review.second_sha256)
    )
    return {(first, second, first_sha, second_sha): decision for first, second, first_sha, second_sha, decision in rows}


def _is_pending_pair(db: Session, dataset_id: str, key: ReviewPair) -> bool:
    first, second, first_sha, second_sha = key
    candidate = {"code": "duplicate_exact", "review_status": "pending"}
    issues = DatasetReportSnapshot.payload["issues"]
    return db.scalar(select(DatasetReportSnapshot.dataset_id).where(
        DatasetReportSnapshot.dataset_id == dataset_id, DatasetReportSnapshot.kind == "duplicates",
        or_(issues.contains([{**candidate, "image_id": first, "related_image_id": second,
                             "image_sha256": first_sha, "related_image_sha256": second_sha}]),
            issues.contains([{**candidate, "image_id": second, "related_image_id": first,
                             "image_sha256": second_sha, "related_image_sha256": first_sha}])),
    )) is not None


def apply_review(
    db: Session, dataset_id: str, image_id: str, related_image_id: str, image_sha256: str, related_image_sha256: str,
    decision: ReviewDecision,
) -> None:
    if decision not in ("keep_both", "discard_image", "discard_related"):
        raise ValueError("请选择保留两张图片或排除一张图片")
    if image_id == related_image_id:
        raise ValueError("重复图审核需要两张不同的图片")
    if image_sha256 != related_image_sha256:
        raise ValueError("只有文件内容相同的图片可以进行重复图审核")
    repository.get_dataset(db, dataset_id, lock=True, include_images=False)
    for sample_id, expected_sha in ((image_id, image_sha256), (related_image_id, related_image_sha256)):
        image = repository.get_image(db, dataset_id, sample_id, include_excluded=True)
        if image.excluded_at is not None:
            raise repository.Conflict("审核图片已排除，请刷新报告")
        record = db.get(DatasetImageAnalysis, sample_id)
        if record is None or record.error is not None or record.sha256 != expected_sha or not signature_matches(image.storage_path, record):
            raise repository.Conflict("审核图片已变化，请重新扫描后再审核")

    key = pair_key(image_id, related_image_id, image_sha256, related_image_sha256)
    previous = db.get(DatasetSimilarityReview, (dataset_id, *key))
    if (previous and previous.decision == "keep_both") or not _is_pending_pair(db, dataset_id, key):
        raise repository.Conflict("该配对已变化或已审核，请刷新报告")

    first, second, first_sha, second_sha = key
    discarded = {"discard_image": image_id, "discard_related": related_image_id}.get(decision)
    if discarded is None:
        stored = decision
    else:
        stored = "discard_first" if discarded == first else "discard_second"
    statement = insert(DatasetSimilarityReview).values(
        dataset_id=dataset_id, first_image_id=first, second_image_id=second,
        first_sha256=first_sha, second_sha256=second_sha, decision=stored,
    )
    db.execute(statement.on_conflict_do_update(
        index_elements=list(DatasetSimilarityReview.__table__.primary_key.columns),
        set_=dict(decision=statement.excluded.decision, reviewed_at=func.clock_timestamp()),
    ))
    if discarded is None:
        invalidate_reports(db, dataset_id, ("duplicates",))
    else:
        service.exclude_image(db, dataset_id, discarded)
    db.commit()
