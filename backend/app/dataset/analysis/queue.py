from collections.abc import Iterable
from datetime import timedelta

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.dataset.analysis.models import REPORT_KINDS, DatasetAnalysisJob, DatasetReportSnapshot, ReportKind
from app.dataset.models import Dataset
from app.dataset.repository import NotFound

Job = DatasetAnalysisJob
Snapshot = DatasetReportSnapshot
DEBOUNCE = timedelta(seconds=2)


def lock_dataset(db: Session, dataset_id: str) -> bool:
    return db.scalar(select(Dataset.id).where(Dataset.id == dataset_id).with_for_update(read=True, key_share=True)) is not None


def invalidate_reports(db: Session, dataset_id: str, kinds: Iterable[ReportKind], *, immediate: bool = False) -> None:
    """Record mutations in the same transaction that writes the dataset."""
    kinds = sorted(set(kinds))
    if not kinds:
        return
    now = func.clock_timestamp()
    priority = int(immediate)
    available_at = now if immediate else now + DEBOUNCE
    statement = insert(Job).values([
        dict(dataset_id=dataset_id, kind=kind, revision=1, status="queued", priority=priority,
             available_at=available_at, attempts=0)
        for kind in kinds
    ])
    manual_pending = and_(Job.status.in_(("queued", "running")), Job.priority > 0)
    db.execute(statement.on_conflict_do_update(
        index_elements=[Job.dataset_id, Job.kind],
        set_=dict(revision=Job.revision + 1, status="queued", attempts=0,
                  available_at=case((manual_pending, now), else_=available_at),
                  priority=case((manual_pending, 1), else_=priority),
                  claim_token=None, lease_until=None, completed=None, total=None, error=None),
    ))


def request_report(db: Session, dataset_id: str, kind: ReportKind, *, force: bool = False) -> None:
    # Match the lock order used by dataset mutations and snapshot publication.
    if not lock_dataset(db, dataset_id):
        raise NotFound("未找到数据集")
    now = func.clock_timestamp()
    statement = insert(Job).values(dataset_id=dataset_id, kind=kind, revision=1, status="queued", priority=1,
                                   available_at=now, attempts=0)
    restart = Job.status == "failed"
    if force:
        restart = or_(restart, Job.status == "ready",
                      and_(Job.status == "running", or_(Job.priority == 0, Job.lease_until <= now)))
    db.execute(statement.on_conflict_do_update(
        index_elements=[Job.dataset_id, Job.kind],
        where=or_(Job.status == "queued", restart),
        set_=dict(revision=case((restart, Job.revision + 1), else_=Job.revision), status="queued",
                  available_at=now, priority=1, attempts=case((restart, 0), else_=Job.attempts),
                  claim_token=None, lease_until=None, completed=None, total=None, error=None),
    ))


def read_report(db: Session, dataset_id: str, kind: ReportKind) -> dict:
    row = db.execute(
        select(Job.status, Job.revision, Job.completed, Job.total, Job.error,
               Snapshot.revision.label("snapshot_revision"), Snapshot.generated_at, Snapshot.payload)
        .select_from(Job)
        .outerjoin(Snapshot, (Snapshot.dataset_id == Job.dataset_id) & (Snapshot.kind == Job.kind))
        .where(Job.dataset_id == dataset_id, Job.kind == kind)
    ).one_or_none()
    if row is None:
        return dict(status="idle", stale=False, generated_at=None, progress=None, error=None, report=None)
    progress = None
    if row.status == "running" and row.completed is not None and row.total is not None:
        progress = dict(completed=row.completed, total=row.total)
    return dict(status=row.status, stale=row.snapshot_revision is not None and row.snapshot_revision != row.revision,
                generated_at=row.generated_at, progress=progress, error=row.error if row.status == "failed" else None,
                report=row.payload)
