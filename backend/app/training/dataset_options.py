"""Training selection summaries without loading image annotations."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dataset.models import Dataset, DatasetImage
from app.training.schemas import TASK_TYPES
from app.training.snapshot import inspect_dataset


def list_datasets(db: Session) -> list[dict]:
    db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
    results = []
    datasets = db.scalars(select(Dataset).where(Dataset.task_type.in_(TASK_TYPES))
                          .order_by(Dataset.created_at.desc(), Dataset.id)).all()
    for dataset in datasets:
        report = inspect_dataset(db, dataset.id, dataset.task_type)
        counts = dict(db.execute(select(DatasetImage.split, func.count()).where(
            DatasetImage.dataset_id == dataset.id, DatasetImage.excluded_at.is_(None),
            DatasetImage.status == "annotated",
        ).group_by(DatasetImage.split)).all())
        results.append({
            **report, "id": dataset.id, "name": dataset.name, "task": dataset.task_type,
            "annotatedSplitCounts": {split: counts.get(split, 0) for split in ("train", "val", "test")},
            "unassignedCount": next((issue["count"] for issue in report["errors"]
                                      if issue["code"] == "SPLIT_UNASSIGNED"), 0),
        })
    return results
