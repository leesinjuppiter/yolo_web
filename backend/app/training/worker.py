"""Single-machine training worker, independent of the API lifecycle."""

import json
import logging
import re
import signal
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from importlib.util import find_spec
from pathlib import Path
from threading import Event
from time import monotonic
from uuid import uuid4

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core.config import data_dir
from app.core.database import engine
from app.training.catalog import expand_arguments, resolve_model
from app.training.devices import DeviceUnavailableError, publish_capabilities, validate_device
from app.training.models import TrainingLog, TrainingMetric, TrainingTask
from app.training.previews import read_previews
from app.training.repository import task_dir, WORKER_LOCK
from app.training.resources import ResourceSampler
from app.training.runner_io import artifact_manifest, failure_for, OutputCapture
from app.training.runner_process import command, run_child, worker_file_lock
from app.training.snapshot import prepare_snapshot, SnapshotError


log = logging.getLogger(__name__)


class Canceled(Exception):
    pass


class WorkerStopping(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _finish(row: TrainingTask, status: str, failure: dict | None = None) -> None:
    row.status = "canceled" if row.cancel_requested else status
    row.failure = failure if row.status == "failed" else None
    if row.status in ("succeeded", "canceled"):
        row.phase = "finished" if row.status == "succeeded" else "canceled"
    row.finished_at = _now()
    row.worker_token = None


def _retained_artifacts(directory: Path) -> list[dict]:
    try:
        return artifact_manifest(directory)
    except OSError:
        log.warning("无法读取任务 %s 的保留文件", directory.name, exc_info=True)
        return []


def _recover() -> None:
    with Session(engine()) as db, db.begin():
        # Older API versions saved unclaimed tasks as created.
        db.execute(update(TrainingTask).where(
            TrainingTask.status == "created", TrainingTask.worker_token.is_(None),
        ).values(status="queued", phase="queued"))
        abandoned = db.scalars(select(TrainingTask.id).where(
            TrainingTask.status.in_(("created", "running")),
            TrainingTask.worker_token.is_not(None),
        )).all()
    for task_id in abandoned:
        artifacts = _retained_artifacts(task_dir(task_id))
        with Session(engine()) as db, db.begin():
            row = db.get(TrainingTask, task_id, with_for_update=True)
            row.artifacts = artifacts
            _finish(row, "failed", {"code": "PROCESS_LOST", "stage": row.phase,
                                    "summary": "训练执行器已中断。", "suggestion": "检查已有日志后重新提交训练。"})


def _claim() -> TrainingTask | None:
    with Session(engine(), expire_on_commit=False) as db, db.begin():
        row = db.scalar(select(TrainingTask).where(
            TrainingTask.status.in_(("created", "queued")), TrainingTask.worker_token.is_(None),
        ).order_by(TrainingTask.created_at, TrainingTask.id)
          .limit(1).with_for_update(skip_locked=True))
        if row is None:
            return None
        row.worker_token = str(uuid4())
        row.heartbeat_at = _now()
        row.status = "running"
        row.phase = "loading" if row.snapshot is not None else "snapshot"
        if row.snapshot is not None:
            row.started_at = _now()
        return row


@contextmanager
def _edit(task: TrainingTask):
    with Session(engine()) as db, db.begin():
        row = db.get(TrainingTask, task.id, with_for_update=True)
        if row is None or row.worker_token != task.worker_token:
            raise WorkerStopping("训练任务所有权已变更")
        row.heartbeat_at = _now()
        yield db, row


def _check(task: TrainingTask, stop: Event) -> None:
    if stop.is_set():
        raise WorkerStopping("训练执行器正在停止")
    publish_capabilities()
    with _edit(task) as (_, row):
        canceled = row.cancel_requested
    if canceled:
        raise Canceled()


def _prepare(task: TrainingTask, directory: Path, check) -> dict:
    if getattr(task, "resume_from_task_id", None):
        from app.training.resume import prepare_resume

        snapshot = prepare_resume(task, directory, check)
    else:
        with Session(engine()) as db:
            snapshot = prepare_snapshot(db, task.dataset_id, task.config["task"], directory / "input",
                                        expected_revision=task.dataset_revision, check_cancel=check)
    for key in ("data_path", "manifest_path"):
        if Path(snapshot[key]).is_absolute():
            snapshot[key] = Path(snapshot[key]).relative_to(directory).as_posix()
    check()
    with _edit(task) as (_, row):
        if row.cancel_requested:
            raise Canceled()
        row.snapshot = snapshot
        row.dataset_image_count = snapshot["image_count"]
        row.dataset_class_count = snapshot["class_count"]
        row.phase = "loading"
        row.started_at = _now()
    return snapshot


def _copy_model(task: TrainingTask, directory: Path, check) -> tuple[Path, str, bool]:
    if (task.snapshot or {}).get("resume_model"):
        return directory / task.snapshot["resume_model"], task.snapshot["resume_sha256"], True
    if task.config["modelId"].startswith("version:"):
        from app.models.sources import resolve_version_model

        with Session(engine()) as db:
            option = resolve_version_model(db, task.config["modelId"])
    else:
        option = resolve_model(task.config["modelId"])
    source = Path(option.source)
    if not option.pretrained:
        package = find_spec("ultralytics")
        if not package or not package.origin:
            raise ValueError("当前训练环境缺少 Ultralytics")
        source = Path(package.origin).parent / "cfg" / "models" / "11" / re.sub(r"^yolo11[nsmlx]", "yolo11", source.name)
    model_directory = directory / "model"
    model_directory.mkdir(exist_ok=True)
    model = model_directory / Path(option.source).name
    digest = sha256()
    with source.open("rb") as input_file, model.open("xb") as output:
        while chunk := input_file.read(1024 * 1024):
            check()
            digest.update(chunk)
            output.write(chunk)
    if option.sha256 and digest.hexdigest() != option.sha256:
        raise ValueError("模型权重校验值与登记版本不一致")
    return model, digest.hexdigest(), option.pretrained


def _invoke(task: TrainingTask, directory: Path, check) -> OutputCapture:
    device = validate_device(task.config["deviceId"], execution=True)
    model, model_hash, pretrained = _copy_model(task, directory, check)
    invocation = {"model": str(model), "task": task.config["task"], "directory": str(directory),
                  "data": str(directory / task.snapshot["data_path"]),
                  "arguments": {**expand_arguments(task.config), "pretrained": pretrained},
                  "resume": bool(getattr(task, "resume_from_task_id", None))}
    (directory / "invocation.json").write_text(json.dumps(invocation, ensure_ascii=False), encoding="utf-8")
    with _edit(task) as (_, row):
        row.environment = {**(row.environment or {}), "python": sys.version, "command": command(directory), "device": device,
                           "modelSource": model.relative_to(directory).as_posix(), "modelSha256": model_hash,
                           "arguments": invocation["arguments"]}
    task.environment = {**(task.environment or {}), "device": device}
    check()
    return OutputCapture(directory)


def _capture(task: TrainingTask, capture: OutputCapture, *, finished: bool = False,
             resource_sample: dict | None = None) -> None:
    logs, events = capture.read(finished=finished)
    with _edit(task) as (db, row):
        if resource_sample is not None:
            row.environment = {**(row.environment or {}), "resourceSample": resource_sample}
        for sequence, level, message in logs:
            db.add(TrainingLog(task_id=row.id, sequence=sequence, level=level, message=message))
        for sequence, event in events:
            if event["kind"] == "metric":
                db.add(TrainingMetric(task_id=row.id, sequence=sequence, epoch=event["epoch"],
                                      values=event["values"], step=event["step"],
                                      elapsed_seconds=event["elapsedSeconds"]))
                row.epoch = event["epoch"]
                row.metrics = event["values"]
            elif event["kind"] == "final_metrics":
                row.metrics = {**row.metrics, **event["values"]}
            elif event["kind"] == "environment":
                row.environment = {**row.environment, **{key: value for key, value in event.items() if key != "kind"}}
            elif event["kind"] == "phase":
                row.phase = event["phase"]


def _train(task: TrainingTask, directory: Path, stop: Event, check) -> None:
    capture = _invoke(task, directory, check)
    try:
        with run_child(directory, task.config["deviceId"]) as child:
            sampler = ResourceSampler(child.pid, device=(task.environment or {}).get("device"))
            with _edit(task) as (_, row):
                row.environment = {**row.environment, "processId": child.pid}
            while child.poll() is None:
                check()
                _capture(task, capture, resource_sample=sampler.sample())
                stop.wait(0.75)
    finally:
        while True:
            _capture(task, capture, finished=True)
            if capture.complete:
                break
    check()
    if child.returncode:
        artifacts = artifact_manifest(directory, check=check)
        with _edit(task) as (_, row):
            row.artifacts = artifacts
            _finish(row, "failed", failure_for(row.phase, child.returncode, capture))
        return
    with _edit(task) as (_, row):
        row.phase = "archiving"
    artifacts = artifact_manifest(directory, check=check)
    required = {"best.pt", "last.pt", "metrics.csv", "training.log"}
    with _edit(task) as (_, row):
        row.artifacts = artifacts
        previews = read_previews(directory)
        artifact_ids = {item["id"] for item in artifacts}
        if previews:
            row.previews = [item for item in previews if {item["artifactId"], item["groundTruthArtifactId"]} <= artifact_ids]
        elif "preview-prediction" in artifact_ids:
            row.previews = [{"id": "validation-batch", "name": "验证集样本 · 最优权重",
                             "artifactId": "preview-prediction", "groundTruthArtifactId": "preview-labels"}]
        if required - {item["name"] for item in artifacts} or row.epoch == 0:
            _finish(row, "failed", {"code": "ARTIFACT_MISSING", "stage": row.phase,
                                    "summary": "训练结束，但缺少有效权重、指标或日志。", "exitCode": child.returncode})
        else:
            _finish(row, "succeeded")


def _process(task: TrainingTask, stop: Event, verify_lock) -> None:
    directory = task_dir(task.id)
    last_check = -float("inf")

    def check(force=False):
        nonlocal last_check
        if force or stop.is_set() or monotonic() - last_check >= 0.75:
            verify_lock()
            _check(task, stop)
            last_check = monotonic()

    try:
        directory.mkdir(parents=True, exist_ok=True)
        check(force=True)
        if task.snapshot is None:
            task.snapshot = _prepare(task, directory, check)
        _train(task, directory, stop, check)
    except (Canceled, SnapshotError, WorkerStopping, DeviceUnavailableError, ValueError) as exc:
        artifacts = _retained_artifacts(directory)
        with _edit(task) as (_, row):
            row.artifacts = artifacts
            if isinstance(exc, Canceled):
                _finish(row, "canceled")
            elif isinstance(exc, SnapshotError):
                _finish(row, "failed", {"code": exc.code, "stage": row.phase, "summary": str(exc),
                                        "details": exc.details})
            elif isinstance(exc, DeviceUnavailableError):
                _finish(row, "failed", {"code": "CUDA_UNAVAILABLE", "stage": row.phase, "summary": str(exc)})
            elif isinstance(exc, ValueError):
                _finish(row, "failed", {"code": "TRAINING_INPUT_INVALID", "stage": row.phase, "summary": str(exc)})
            else:
                _finish(row, "failed", {"code": "WORKER_STOPPED", "stage": row.phase, "summary": str(exc)})
    except Exception:
        log.exception("训练任务 %s 执行失败", task.id)
        artifacts = _retained_artifacts(directory)
        with _edit(task) as (_, row):
            row.artifacts = artifacts
            _finish(row, "failed", {"code": "WORKER_ERROR", "stage": row.phase,
                                    "summary": "执行器未能完成任务，请检查训练日志和服务日志。"})


def run_worker(stop: Event) -> None:
    while not stop.is_set():
        try:
            with worker_file_lock(data_dir() / "training") as acquired:
                if acquired:
                    _run_queue(stop)
            stop.wait(1)
        except Exception:
            log.exception("训练执行器无法处理队列")
            stop.wait(2)


def _run_queue(stop: Event) -> None:
    with engine().connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        if not connection.scalar(text("select pg_try_advisory_lock(:key)"), {"key": WORKER_LOCK}):
            return
        try:
            publish_capabilities(force=True)
            _recover()
            while not stop.is_set():
                publish_capabilities()
                connection.execute(text("select 1"))
                task = _claim()
                if task is None:
                    stop.wait(0.75)
                else:
                    _process(task, stop, lambda: connection.execute(text("select 1")))
        finally:
            if not connection.invalidated:
                connection.execute(text("select pg_advisory_unlock(:key)"), {"key": WORKER_LOCK})


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    stop = Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    run_worker(stop)


if __name__ == "__main__":
    main()
