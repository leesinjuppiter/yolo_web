from collections.abc import Iterator
from hashlib import file_digest
from pathlib import Path
from uuid import UUID

from sqlalchemy import Float, cast, extract, func, or_, select, text
from sqlalchemy.orm import Session

from app.core.config import data_dir
from app.dataset.repository import Conflict, NotFound
from app.models.training_versions import ModelVersion
from app.training.models import TrainingLog, TrainingMetric, TrainingTask
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


def log_query(task_id: str, after: int = 0):
    return (select(TrainingLog.sequence, TrainingLog.time, TrainingLog.level, TrainingLog.message)
            .where(TrainingLog.task_id == task_id, TrainingLog.sequence > after).order_by(TrainingLog.sequence))


def export_log(db: Session, task_id: str) -> Iterator[str]:
    bind = db.get_bind()
    with Session(bind) as lookup:
        require_task(lookup, task_id)
    labels = {"info": "INFO", "warn": "WARNING", "error": "ERROR", "metric": "METRICS"}

    def stream() -> Iterator[str]:
        # Own the cursor and its session for the entire HTTP stream.
        with Session(bind) as session, session.execute(log_query(task_id).execution_options(yield_per=256)) as rows:
            for batch in rows.partitions(256):
                yield "".join(f"[{row.time.isoformat()}] [{labels.get(row.level, row.level.upper())}] {row.message}\n"
                              for row in batch)

    return stream()


def recent_epoch_timings(db: Session, task_id: str, epoch: int) -> list[tuple[int, float]]:
    rows = db.execute(select(TrainingMetric.epoch, TrainingMetric.elapsed_seconds)
                      .where(TrainingMetric.task_id == task_id, TrainingMetric.epoch <= epoch,
                             TrainingMetric.elapsed_seconds.is_not(None))
                      .order_by(TrainingMetric.sequence.desc()).limit(4))
    return [(row.epoch, row.elapsed_seconds) for row in rows]


def reserve_task_name(db: Session, name: str) -> None:
    normalized = db.scalar(select(func.lower(name)))
    # Serialize creation by name, including requests with different idempotency keys.
    db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"training-name:{normalized}", 0))))
    existing = db.scalar(select(TrainingTask.id).where(
        func.lower(func.btrim(TrainingTask.config["name"].astext)) == normalized,
    ).limit(1))
    if existing is not None:
        raise Conflict("训练任务名称已存在，请使用其他名称")


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


def verified_artifact_file(task: TrainingTask, artifact_id: str) -> tuple[dict, Path]:
    item, path = artifact_file(task, artifact_id)
    with path.open('rb') as source:
        digest = file_digest(source, 'sha256').hexdigest()
    if item['sha256'] != digest:
        raise Conflict('最优权重的文件校验值与训练记录不一致')
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
    # Runs can use different validation inputs; their arithmetic mean is not a model score.
    average = None
    summary = {
        "total": total, "page": page, "pageSize": page_size, "averageScore": average,
        "architectures": list(db.scalars(select(TrainingTask.architecture).distinct().order_by(TrainingTask.architecture))),
        "statusCounts": dict(db.execute(select(TrainingTask.status, func.count())
                                        .group_by(TrainingTask.status)).all()),
        "elapsedTotal": float(db.scalar(select(func.sum(_elapsed()))) or 0),
        "scoreComparability": "Metrics may use different validation inputs; compare only matched evaluations.",
    }
    return rows, summary

