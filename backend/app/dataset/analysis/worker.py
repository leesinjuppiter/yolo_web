import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from threading import Event, Thread
from time import monotonic
from uuid import uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.database import engine
from app.dataset.analysis.models import ReportKind
from app.dataset.analysis.queue import Job, Snapshot, lock_dataset

log = logging.getLogger(__name__)
Progress = Callable[[int, int], None]
ComputeReport = Callable[[str, ReportKind, Progress], dict]
MAX_ATTEMPTS = 3
LEASE = timedelta(seconds=30)


@dataclass(frozen=True)
class Claim:
    dataset_id: str
    kind: ReportKind
    revision: int
    token: str
    attempts: int

    def matches(self):
        return and_(Job.dataset_id == self.dataset_id, Job.kind == self.kind, Job.revision == self.revision,
                    Job.claim_token == self.token, Job.status == "running")


def _claim() -> Claim | None:
    with Session(engine()) as db, db.begin():
        now = func.clock_timestamp()
        expired = and_(Job.status == "running", Job.lease_until <= now)
        db.execute(update(Job).where(expired, Job.attempts >= MAX_ATTEMPTS).values(
            status="failed", claim_token=None, lease_until=None, error="分析任务多次中断，请重试",
        ))
        job = db.scalar(select(Job).where(
            or_(and_(Job.status == "queued", Job.available_at <= now), expired),
            Job.attempts < MAX_ATTEMPTS,
        ).order_by(Job.priority.desc(), Job.available_at, Job.dataset_id, Job.kind).limit(1).with_for_update(skip_locked=True))
        if job is None:
            return None
        token = str(uuid4())
        job.status, job.claim_token, job.lease_until = "running", token, now + LEASE
        job.attempts += 1
        job.completed = job.total = None
        return Claim(job.dataset_id, job.kind, job.revision, token, job.attempts)


def _heartbeat(claim: Claim, stop: Event) -> None:
    while not stop.wait(10):
        try:
            with Session(engine()) as db, db.begin():
                renewed = db.scalar(update(Job).where(claim.matches()).values(
                    lease_until=func.clock_timestamp() + LEASE,
                ).returning(Job.revision))
            if renewed is None:
                return
        except Exception:
            log.exception("Could not renew report lease for %s %s", claim.dataset_id, claim.kind)


def _progress(claim: Claim) -> Progress:
    last = float("-inf")
    previous = None

    def report(completed: int, total: int) -> None:
        nonlocal last, previous
        now = monotonic()
        if previous == (completed, total) or (completed != total and now - last < 0.35):
            return
        with Session(engine()) as db, db.begin():
            db.execute(update(Job).where(claim.matches()).values(completed=completed, total=total))
        last, previous = now, (completed, total)

    return report


def _publish(claim: Claim, payload: dict) -> None:
    with Session(engine()) as db, db.begin():
        if not lock_dataset(db, claim.dataset_id):
            return
        revision = db.scalar(update(Job).where(claim.matches()).values(
            status="ready", claim_token=None, lease_until=None, completed=None, total=None, error=None,
        ).returning(Job.revision))
        if revision is None:
            return
        statement = insert(Snapshot).values(dataset_id=claim.dataset_id, kind=claim.kind, revision=revision,
                                            generated_at=func.clock_timestamp(), payload=payload)
        db.execute(statement.on_conflict_do_update(index_elements=[Snapshot.dataset_id, Snapshot.kind], set_=dict(
            revision=statement.excluded.revision, generated_at=statement.excluded.generated_at,
            payload=statement.excluded.payload,
        )))


def _fail(claim: Claim) -> None:
    exhausted = claim.attempts >= MAX_ATTEMPTS
    with Session(engine()) as db, db.begin():
        db.execute(update(Job).where(claim.matches()).values(
            status="failed" if exhausted else "queued", claim_token=None, lease_until=None, completed=None, total=None,
            available_at=func.clock_timestamp() + timedelta(seconds=2 ** claim.attempts),
            error="分析暂时失败，请重试" if exhausted else None,
        ))


def process_next(compute: ComputeReport) -> bool:
    claim = _claim()
    if claim is None:
        return False
    stop_heartbeat = Event()
    heartbeat = Thread(target=_heartbeat, args=(claim, stop_heartbeat), name="report-lease", daemon=True)
    heartbeat.start()
    try:
        _publish(claim, compute(claim.dataset_id, claim.kind, _progress(claim)))
    except Exception:
        log.exception("Dataset report failed for %s %s", claim.dataset_id, claim.kind)
        _fail(claim)
    finally:
        stop_heartbeat.set()
        heartbeat.join(timeout=0.2)
    return True


def run_worker(stop: Event, compute: ComputeReport) -> None:
    while not stop.is_set():
        try:
            if not process_next(compute):
                stop.wait(0.5)
        except Exception:
            log.exception("Dataset report worker could not reach the queue")
            stop.wait(2)
