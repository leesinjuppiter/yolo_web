"""Serial, CPU-only model evaluation worker. Owns one advisory lock."""
import json
import os
import re
import shutil
from hashlib import file_digest
import signal
import subprocess
import sys
from threading import Event
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.database import engine
from app.evaluation.models import EvaluationRun
from app.evaluation.repository import evaluation_dir, get_run, log
from app.evaluation.snapshot import prepare_snapshot, validate_source
from app.models.sources import registered_asset
from app.training.repository import get_task

LOCK = 154026221043
MODEL_COMPUTE_LOCK = 154026221042


def safe_tail(path) -> list[str]:
    with path.open("rb") as source:
        source.seek(max(0, path.stat().st_size - 16384))
        lines = source.read().decode("utf-8", errors="replace").splitlines()[-15:]
    result = []
    for line in lines:
        if re.search(r"password|token|secret|postgresql://|PRIVATE KEY", line, re.IGNORECASE):
            continue
        line = re.sub(r"(?:[A-Za-z]:[\\/]|/)[^\s\"'<>]+", "[path]", line)
        result.append(line[:500])
    return result


def _finish(run_id: str, status: str, report=None, error=None):
    with Session(engine()) as db, db.begin():
        row = get_run(db, run_id, True)
        row.status, row.phase = status, status
        row.report, row.error = report, error
        row.finished_at = datetime.now(timezone.utc)
        log(row, "评估完成" if status == "succeeded" else error or "评估已取消",
            "error" if status == "failed" else "info")


def _execute(run_id: str, stop: Event):
    folder = evaluation_dir(run_id)
    folder.mkdir(parents=True, exist_ok=True)
    with Session(engine()) as db:
        row = get_run(db, run_id)
        version, task, _, model_path = registered_asset(db, "version:" + row.version_id)
        source = get_task(db, row.config["sourceTaskId"]) if row.config.get("sourceTaskId") else task
        purpose = row.config.get("purpose", "final")
        split = "val" if purpose == "diagnostic" else "test"
        validate_source(task, source, split)
        snapshot = prepare_snapshot(source, folder / "input", split)
        frozen_model = folder / "model.pt"
        shutil.copyfile(model_path, frozen_model)
        with frozen_model.open("rb") as checkpoint:
            if file_digest(checkpoint, "sha256").hexdigest() != version.sha256:
                raise ValueError("复制期间模型权重已变化")
        job = {"directory": str(folder), "modelPath": str(frozen_model), "modelSha256": version.sha256,
               "snapshot": snapshot, "taskType": task.config["task"], "imgsz": row.config["imgsz"],
               "purpose": purpose, "sourceTaskId": source.id,
               "diagnosticConf": row.config.get("diagnosticConf", 0.25),
               "diagnosticIou": row.config.get("diagnosticIou", 0.5)}
    (folder / "job.json").write_text(json.dumps(job), encoding="utf-8")
    with Session(engine()) as db, db.begin():
        row = get_run(db, run_id, True)
        row.phase = "evaluating"
        log(row, f"{split} 快照已冻结并校验；在 CPU 上执行评估")
    environment = {**os.environ, "CUDA_VISIBLE_DEVICES": "-1", "YOLO_AUTOINSTALL": "False"}
    with (folder / "stdout.log").open("wb") as output:
        child = subprocess.Popen([sys.executable, "-m", "app.evaluation.runner", str(folder / "job.json")],
                                 stdout=output, stderr=subprocess.STDOUT, env=environment)
        while child.poll() is None:
            with Session(engine()) as db:
                canceled = get_run(db, run_id).cancel_requested
            if canceled or stop.is_set():
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
                _finish(run_id, "canceled" if canceled else "failed",
                        error=None if canceled else "评估执行器已停止，请新建任务重试")
                return
            stop.wait(0.5)
    if child.returncode:
        with Session(engine()) as db, db.begin():
            row = get_run(db, run_id, True)
            for message in safe_tail(folder / "stdout.log"):
                log(row, message, "error")
        raise RuntimeError("评估进程失败，请检查执行器日志；未生成有效报告")
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    # Internal paths are kept in the job directory, not in API reports.
    report["snapshot"].pop("dataPath", None)
    _finish(run_id, "succeeded", report=report)


def main():
    stop = Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    with engine().connect() as connection:
        if not connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK}):
            raise RuntimeError("已有评估执行器正在运行")
        with Session(engine()) as db, db.begin():
            for row in db.scalars(select(EvaluationRun).where(EvaluationRun.status == "running")):
                row.status, row.phase, row.error = "failed", "failed", "评估执行器中断，请新建任务重试"
                row.finished_at = datetime.now(timezone.utc)
        while not stop.is_set():
            with Session(engine()) as db, db.begin():
                row = db.scalar(select(EvaluationRun).where(EvaluationRun.status == "queued",
                    EvaluationRun.cancel_requested.is_(False)).order_by(EvaluationRun.created_at).limit(1).with_for_update(skip_locked=True))
                run_id = row.id if row else None
                if row:
                    row.status, row.phase = "running", "snapshot"
                    row.started_at = datetime.now(timezone.utc)
            if run_id:
                try:
                    with engine().connect() as compute:
                        while not stop.is_set():
                            if compute.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": MODEL_COMPUTE_LOCK}):
                                break
                            stop.wait(0.5)
                        try:
                            if stop.is_set():
                                _finish(run_id, "failed", error="评估执行器已停止，请新建任务重试")
                            else:
                                _execute(run_id, stop)
                        finally:
                            compute.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": MODEL_COMPUTE_LOCK})
                except Exception as exc:
                    print(f"Evaluation {run_id} failed: {exc}", file=sys.stderr)
                    _finish(run_id, "failed", error="评估失败：" + str(exc)[:500]
                            if isinstance(exc, ValueError) else "评估执行失败；请检查快照、依赖及执行器日志")
            else:
                stop.wait(1)


if __name__ == "__main__":
    main()
