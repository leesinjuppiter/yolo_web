"""Single recommendation worker; start separately from the API."""
from datetime import datetime, timezone
import signal
import subprocess
from threading import Event

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.active_learning import execution, repository as repo
from app.active_learning.models import Iteration, RecommendationTask
from app.active_learning.review import upsert_candidate
from app.core.database import engine
from app.evaluation.models import EvaluationRun
from app.models.sources import registered_asset
from app.training.compute import device_slot

LOCK = 154026221045


def check(identifier, stop):
    with Session(engine()) as db:
        row = repo.get(db, RecommendationTask, identifier)
        if stop.is_set() or row.cancel_requested:
            raise InterruptedError("推荐任务已取消")


def update(identifier, **values):
    with Session(engine()) as db, db.begin():
        row = repo.get(db, RecommendationTask, identifier, True)
        for key, value in values.items():
            setattr(row, key, value)


def references(db, task, iteration):
    if task.config["strategy"] == "low_confidence":
        return
    from app.evaluation.service import image_detail
    run = repo.get(db, EvaluationRun, task.config["evaluationId"])
    errors = [row for row in run.report["perImage"] if row["fp"] or row["fn"]]
    errors.sort(key=lambda row: (-row["fn"], -row["fp"], row["imageId"]))
    for row in errors[:task.config["referenceLimit"]]:
        detail = image_detail(db, run.id, row["imageId"])
        upsert_candidate(db, iteration, row["imageId"], "reference", {
            "name": row["name"], "reasons": [name for name, count in (("false_negative", row["fn"]),
            ("false_positive", row["fp"])) if count], "taskIds": [task.id], "evaluationId": run.id,
            "diagnostic": detail}, task.id)


def execute(identifier, stop):
    with Session(engine()) as db:
        task = repo.get(db, RecommendationTask, identifier)
        iteration = repo.get(db, Iteration, task.iteration_id)
        _, _, _, model = registered_asset(db, "version:" + iteration.baseline_version_id)
        device = task.config["deviceId"]
        config = task.config
        db.expunge(task)
        db.expunge(iteration)
    check(identifier, stop)
    with Session(engine()) as db, db.begin():
        references(db, task, iteration)
    if config["strategy"] != "error_first":
        with device_slot(device, lambda: check(identifier, stop), lambda: update(identifier, phase="waiting_device")):
            check(identifier, stop)
            update(identifier, phase="predicting")
            process = execution.start(task, iteration, model)
            try:
                while process.poll() is None:
                    check(identifier, stop)
                    update(identifier, processed=execution.read_progress(identifier))
                    stop.wait(.5)
                if process.returncode:
                    raise RuntimeError("推荐推理进程失败，请检查主动学习执行器日志")
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
        check(identifier, stop)
        with Session(engine()) as db, db.begin():
            for value in execution.read_result(identifier):
                upsert_candidate(db, iteration, value["imageId"], "training",
                                 {**value, "taskIds": [identifier]}, identifier)
    update(identifier, status="succeeded", phase="succeeded", processed=task.total,
           finished_at=datetime.now(timezone.utc))


def main():
    stop = Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    with engine().connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        if not connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK}):
            raise RuntimeError("已有主动学习执行器运行")
        with Session(engine()) as db, db.begin():
            for row in db.scalars(select(RecommendationTask).where(RecommendationTask.status == "running")):
                row.status = row.phase = "failed"
                row.error = "执行器中断，请按原配置新建任务"
        while not stop.is_set():
            with Session(engine()) as db, db.begin():
                task = db.scalar(select(RecommendationTask).where(RecommendationTask.status == "queued")
                    .order_by(RecommendationTask.created_at).with_for_update(skip_locked=True).limit(1))
                identifier = task.id if task else None
                if task:
                    task.status, task.phase = "running", "preparing"
            if not identifier:
                stop.wait(1)
                continue
            try:
                execute(identifier, stop)
            except Exception as error:
                update(identifier, status="canceled" if isinstance(error, InterruptedError) else "failed",
                    phase="canceled" if isinstance(error, InterruptedError) else "failed", error=str(error)[:1000],
                    finished_at=datetime.now(timezone.utc))


if __name__ == "__main__":
    main()
