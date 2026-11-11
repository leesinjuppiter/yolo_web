"""Serial CPU export/package worker. Start separately from the API process."""

import json
import logging
import os
import signal
import shutil
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Event

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.database import engine
from app.deployment.builder import build
from app.deployment.models import DeploymentPackage
from app.evaluation.snapshot import prepare_test_snapshot
from app.model_exports.models import ExportTask
from app.model_exports.storage import digest, export_dir, package_dir, write_json
from app.models.sources import registered_asset
from app.training.runner_process import OutputTail, child_environment, worker_file_lock

LOCK = 154026221041
log = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc)


def append(row, message: str, level: str = "info") -> None:
    # Strip task-local absolute paths from public logs.
    from app.core.config import data_dir
    clean = message.replace(str(data_dir()), "<data>").replace(str(Path(__file__).resolve().parents[2]), "<backend>")
    previous = row.logs or []
    row.logs = [*previous, {"sequence": previous[-1]["sequence"]+1 if previous else 1,
                          "time": now().isoformat(), "level": level, "message": clean[:4000]}][-1000:]


def finish(row, status: str, error: str | None = None) -> None:
    from app.core.config import data_dir
    error = error.replace(str(data_dir()), "<data>") if error else None
    row.status, row.phase, row.error = status, status, error
    row.finished_at = now()
    append(row, error or ("任务完成" if status == "succeeded" else "任务已取消"), "error" if error else "info")


def _claim(model):
    with Session(engine(), expire_on_commit=False) as db, db.begin():
        row = db.scalar(select(model).where(model.status == "queued").order_by(model.created_at)
                        .with_for_update(skip_locked=True).limit(1))
        if row:
            row.status, row.phase, row.started_at = "running", "preparing", now()
            append(row, "执行器已领取任务")
        return row.id if row else None


def _prepare(task_id: str) -> Path:
    directory = export_dir(task_id)
    directory.mkdir(parents=True, exist_ok=False)
    with Session(engine()) as db:
        row = db.get(ExportTask, task_id)
        version, task, _, source = registered_asset(db, row.version_id)
        if version.lifecycle == "archived":
            raise ValueError("模型已归档，无法执行新的导出")
        if task.config["task"] not in ("detect", "obb"):
            raise ValueError("不支持的导出任务类型")
        shutil.copyfile(source, directory/"source.pt")
        if digest(directory/"source.pt") != version.sha256:
            raise ValueError("复制的注册权重校验失败")
        config = {"task": task.config["task"], "imgsz": row.config["imgsz"],
                  "sourceSha256": version.sha256, "classNames": []}
        try:
            config["snapshot"] = prepare_test_snapshot(task, directory/"test-snapshot")
            config["classNames"] = config["snapshot"]["classNames"]
        except ValueError as exc:
            config["snapshotError"] = str(exc)
        write_json(directory/"invocation.json", config)
    return directory


@contextmanager
def child(directory: Path):
    environment = {**child_environment(directory, "cpu"), "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2",
                   "OPENBLAS_NUM_THREADS": "2"}
    with (directory/"export.log").open("ab", buffering=0) as output:
        process = subprocess.Popen([sys.executable, "-B", "-u", "-m", "app.model_exports.runner",
                                    str(directory/"invocation.json")], stdin=subprocess.PIPE,
                                   stdout=output, stderr=subprocess.STDOUT, env=environment,
                                   start_new_session=os.name != "nt")
        try:
            process.stdin.write(b"1")
            process.stdin.flush()
            yield process
        finally:
            if os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif process.poll() is None:
                process.kill()
            process.stdin.close()
            process.wait(timeout=10)


def execute_export(task_id: str, stop: Event) -> None:
    directory = _prepare(task_id)
    tail = OutputTail(directory/"export.log", progress_lines=True)
    with child(directory) as process:
        while True:
            ended = process.poll() is not None
            with Session(engine()) as db, db.begin():
                row = db.get(ExportTask, task_id, with_for_update=True)
                for line in tail.read(finished=ended):
                    if line.startswith("WORKBENCH_PHASE="):
                        row.phase = line.split("=", 1)[1]
                    else:
                        append(row, line)
                if row.cancel_requested:
                    finish(row, "canceled")
                    return
                if stop.is_set():
                    finish(row, "failed", "导出执行器已停止；请重新创建任务")
                    return
                if ended:
                    if process.returncode:
                        finish(row, "failed", "导出或验证失败，请查看任务日志")
                    else:
                        row.report = json.loads((directory/"report.json").read_text(encoding="utf-8"))
                        finish(row, "succeeded")
                    return
            stop.wait(0.5)


def execute_package(package_id: str) -> None:
    with Session(engine()) as db:
        row = db.get(DeploymentPackage, package_id)
        export = db.get(ExportTask, row.export_id)
        export_id, version_id = export.id, export.version_id
        expected_report = export.report
        version, _, _, _ = registered_asset(db, version_id)
        if version.lifecycle == "archived":
            raise ValueError("模型已归档，无法构建新的部署包")
        if export.status != "succeeded":
            raise ValueError("导出任务未成功，不能构建部署包")
    manifest = build(export_dir(export_id), package_dir(package_id), package_id=package_id,
                     export_id=export_id, version_id=version_id, expected_report=expected_report)
    with Session(engine()) as db, db.begin():
        row = db.get(DeploymentPackage, package_id, with_for_update=True)
        row.manifest = manifest
        finish(row, "succeeded")


def run_worker(stop: Event) -> None:
    from app.core.config import data_dir
    with worker_file_lock(data_dir()/"model_exports") as acquired:
        if not acquired:
            raise RuntimeError("导出执行器已在运行")
        with engine().connect() as connection:
            if not connection.scalar(text("SELECT pg_try_advisory_lock(:lock)"), {"lock": LOCK}):
                raise RuntimeError("导出执行器已在运行")
            try:
                with Session(engine()) as db, db.begin():
                    for model in (ExportTask, DeploymentPackage):
                        for row in db.scalars(select(model).where(model.status == "running")):
                            finish(row, "failed", "上次执行器中断，请新建任务重试")
                while not stop.is_set():
                    worked = False
                    for model, execute in ((ExportTask, lambda ident: execute_export(ident, stop)),
                                           (DeploymentPackage, execute_package)):
                        ident = _claim(model)
                        if ident:
                            worked = True
                            try:
                                with engine().connect() as compute:
                                    while not compute.scalar(text("SELECT pg_try_advisory_lock(:lock)"), {"lock": 154026221042}):
                                        if stop.wait(0.5):
                                            raise RuntimeError("等待计算资源时执行器停止")
                                    try:
                                        execute(ident)
                                    finally:
                                        compute.execute(text("SELECT pg_advisory_unlock(:lock)"), {"lock": 154026221042})
                            except Exception as exc:
                                log.exception("Model asset task failed")
                                with Session(engine()) as db, db.begin():
                                    finish(db.get(model, ident), "failed", str(exc)[:500])
                    if not worked:
                        stop.wait(1)
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(:lock)"), {"lock": LOCK})


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    stop = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    run_worker(stop)


if __name__ == "__main__":
    main()
