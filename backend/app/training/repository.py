from pathlib import Path
from uuid import UUID

from sqlalchemy import Float, cast, extract, func, or_, select, text
from sqlalchemy.orm import Session

from app.core.config import data_dir
from app.dataset.repository import NotFound
from app.models.training_versions import ModelVersion
from app.training.models import TrainingTask
from app.training.schemas import QUALITY_METRIC

WORKER_LOCK = 154026221039


def worker_available(db: Session) -> bool:
    return bool(db.scalar(text("""
        SELECT EXISTS (
            SELECT 1 FROM pg_locks
            WHERE locktype = 'advisory' AND granted AND mode = 'ExclusiveLock'
              AND database = (SELECT oid FROM pg_database WHERE datname = current_database())
              AND objsubid = 1 AND classid = :class_id AND objid = :object_id
        )
    """), {"class_id": WORKER_LOCK >> 32, "object_id": WORKER_LOCK & 0xFFFFFFFF}))


def task_dir(task_id: str) -> Path:
    return data_dir() / "training" / str(UUID(task_id))


def get_task(db: Session, task_id: str, *, lock: bool = False) -> TrainingTask:
    statement = select(TrainingTask).where(TrainingTask.id == task_id)
    task = db.scalar(statement.with_for_update() if lock else statement)
    if task is None:
        raise NotFound("未找到训练任务")
    return task


def require_task(db: Session, task_id: str) -> None:
    if db.scalar(select(TrainingTask.id).where(TrainingTask.id == task_id)) is None:
        raise NotFound("未找到训练任务")


def get_model_version(db: Session, task_id: str) -> ModelVersion | None:
    return db.scalar(select(ModelVersion).where(ModelVersion.task_id == task_id))


def artifact_file(task: TrainingTask, artifact_id: str) -> tuple[dict, Path]:
    item = next((artifact for artifact in task.artifacts if artifact["id"] == artifact_id), None)
    if item is None:
        raise NotFound("未找到训练产物")
    root = task_dir(task.id).resolve()
    path = (root / item["path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise NotFound("训练产物文件不存在")
    return item, path


def _score(task_type: str):
    return cast(TrainingTask.metrics[QUALITY_METRIC[task_type]].astext, Float)


def _elapsed():
    return extract("epoch", func.coalesce(TrainingTask.finished_at, func.now()) - TrainingTask.started_at)


def training_overview(db: Session, *, status: str | None, task_type: str | None, architecture: str | None,
                      query: str, sort: str, page: int, page_size: int) -> tuple[list, dict]:
    clauses = []
    task_kind = TrainingTask.config["task"].astext
    if status:
        clauses.append(TrainingTask.status == status)
    if task_type:
        clauses.append(task_kind == task_type)
    if architecture:
        clauses.append(TrainingTask.architecture == architecture)
    if query:
        fields = (TrainingTask.config["name"].astext, TrainingTask.dataset_name,
                  TrainingTask.model_name, TrainingTask.architecture)
        clauses.append(or_(*(func.lower(field).contains(query.lower(), autoescape=True) for field in fields)))
    order = [TrainingTask.created_at.desc(), TrainingTask.id.desc()]
    if sort == "progress":
        order.insert(0, (cast(TrainingTask.epoch, Float) / cast(TrainingTask.config["epochs"].astext, Float)).desc())
    if sort == "duration":
        order.insert(0, _elapsed().desc().nulls_last())
    if sort == "metric" and task_type:
        order.insert(0, _score(task_type).desc().nulls_last())
    total = db.scalar(select(func.count()).select_from(TrainingTask).where(*clauses))
    page = min(page, max(1, (total + page_size - 1) // page_size))
    rows = db.execute(select(TrainingTask, ModelVersion)
                      .outerjoin(ModelVersion, ModelVersion.task_id == TrainingTask.id)
                      .where(*clauses).order_by(*order).offset((page - 1) * page_size).limit(page_size)).all()
    average = db.scalar(select(func.avg(_score(task_type))).where(
        task_kind == task_type, TrainingTask.status == "succeeded")) if task_type else None
    summary = {
        "total": total, "page": page, "pageSize": page_size, "averageScore": average,
        "architectures": list(db.scalars(select(TrainingTask.architecture).distinct().order_by(TrainingTask.architecture))),
        "statusCounts": dict(db.execute(select(TrainingTask.status, func.count())
                                        .group_by(TrainingTask.status)).all()),
        "elapsedTotal": float(db.scalar(select(func.sum(_elapsed()))) or 0),
    }
    return rows, summary

