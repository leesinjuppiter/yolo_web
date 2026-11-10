from collections.abc import Callable
from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import engine
from app.dataset import repository
from app.dataset.analysis import queue
from app.dataset.models import Dataset
from app.quality.fingerprints import inspect_dataset_files
from app.quality.report import duplicate_report, quality_report
from app.quality.review import load_review_decisions
from app.validation.report import DatasetReport, validate_dataset


class ReportProgress(BaseModel):
    completed: int
    total: int


class ReportSnapshot(BaseModel):
    status: Literal["idle", "queued", "running", "ready", "failed"]
    stale: bool
    generated_at: datetime | None
    progress: ReportProgress | None
    error: str | None
    report: DatasetReport | None


def read_snapshot(db: Session, dataset_id: str, kind: queue.ReportKind) -> ReportSnapshot:
    if db.get(Dataset, dataset_id) is None:
        raise repository.NotFound("未找到数据集")
    return ReportSnapshot.model_validate(queue.read_report(db, dataset_id, kind))


def refresh_report(db: Session, dataset_id: str, kind: queue.ReportKind, *, force: bool) -> ReportSnapshot:
    kinds = ("duplicates", "validate") if force and kind != "quality" else (kind,)
    for affected in kinds:
        queue.request_report(db, dataset_id, affected, force=force)
    snapshot = ReportSnapshot.model_validate(queue.read_report(db, dataset_id, kind))
    db.commit()
    return snapshot


def compute_report(dataset_id: str, kind: queue.ReportKind, progress: Callable[[int, int], None]) -> dict:
    if kind == "duplicates":
        with Session(engine()) as db:
            sources = repository.list_image_sources(db, dataset_id)
            reviews = load_review_decisions(db, dataset_id)
        facts = inspect_dataset_files(dataset_id, sources, progress)
        report = duplicate_report([(image.name, image.storage_path) for image in sources], facts,
                                  image_ids=[image.id for image in sources], reviews=reviews)
    elif kind == "validate":
        with Session(engine()) as db:
            dataset = repository.get_dataset(db, dataset_id)
        facts = inspect_dataset_files(dataset_id, dataset.images, progress)
        report = validate_dataset(dataset, facts)
    else:
        with Session(engine()) as db:
            dataset = repository.get_dataset(db, dataset_id, include_images=False)
            report = quality_report(dataset, *repository.quality_counts(db, dataset_id))
        progress(1, 1)
    return report.model_dump(mode="json")
