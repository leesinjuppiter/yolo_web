from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dataset.repository import Conflict, NotFound
from app.models.sources import registered_asset
from app.model_exports.models import ExportTask
from app.model_exports.schemas import ExportRequest
from app.model_exports.storage import digest, export_dir


def get_task(db: Session, task_id: str) -> ExportTask:
    row = db.get(ExportTask, task_id)
    if row is None:
        raise NotFound("导出任务不存在")
    return row


def response(row: ExportTask) -> dict:
    return {"id": row.id, "versionId": row.version_id, "config": row.config, "status": row.status,
            "phase": row.phase, "createdAt": row.created_at, "startedAt": row.started_at,
            "finishedAt": row.finished_at, "error": row.error, "report": row.report,
            "logs": row.logs, "cancelRequested": row.cancel_requested,
            "downloadUrl": f"/api/exports/{row.id}/download" if row.status == "succeeded" else None}


def create(db: Session, request: ExportRequest, key: str | None) -> dict:
    config = {**request.model_dump(mode="json"), "format": "onnx", "precision": "fp32"}
    with db.begin():
        if key:
            db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"export:{key}", 0))))
            existing = db.scalar(select(ExportTask).where(ExportTask.idempotency_key == key))
            if existing:
                if existing.config != config:
                    raise Conflict("幂等键已用于其他导出配置")
                return response(existing)
        version, task, _, _ = registered_asset(db, str(request.versionId))
        if version.lifecycle == "archived":
            raise Conflict("归档模型不能创建新的导出任务")
        if task.config["task"] not in ("detect", "obb"):
            raise ValueError("首轮只开放 Detect/OBB 的 ONNX FP32 导出")
        row = ExportTask(version_id=str(request.versionId), config=config, idempotency_key=key)
        db.add(row)
        db.flush()
        return response(row)


def overview(db: Session, page: int, page_size: int) -> dict:
    rows = db.scalars(select(ExportTask).order_by(ExportTask.created_at.desc()).offset((page-1)*page_size).limit(page_size))
    return {"items": [response(row) for row in rows], "total": db.scalar(select(func.count()).select_from(ExportTask)),
            "page": page, "pageSize": page_size}


def detail(db: Session, task_id: str) -> dict:
    return response(get_task(db, task_id))


def logs(db: Session, task_id: str, after: int) -> dict:
    items = [item for item in get_task(db, task_id).logs if item["sequence"] > after]
    return {"items": items, "nextSequence": items[-1]["sequence"] if items else after}


def cancel(db: Session, task_id: str) -> dict:
    with db.begin():
        row = db.get(ExportTask, task_id, with_for_update=True)
        if row is None:
            raise NotFound("导出任务不存在")
        if row.status in ("queued", "running"):
            row.cancel_requested = True
            if row.status == "queued":
                row.status, row.phase = "canceled", "canceled"
                row.finished_at = datetime.now(timezone.utc)
        return response(row)


def download(db: Session, task_id: str):
    row = get_task(db, task_id)
    path = export_dir(task_id) / "model.onnx"
    if row.status != "succeeded" or not path.is_file():
        raise Conflict("导出产物尚未生成或已丢失")
    if digest(path) != row.report["artifact"]["sha256"]:
        raise Conflict("导出产物校验失败")
    return path


TOOLS = {"model.export_onnx": create, "model.export_list": overview, "model.export_status": detail,
         "model.export_logs": logs, "model.export_cancel": cancel, "model.export_download": download}
