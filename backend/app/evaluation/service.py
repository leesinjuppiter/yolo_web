from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dataset.repository import Conflict
from app.evaluation.models import EvaluationRun
from app.evaluation.repository import get_run, response
from app.evaluation.schemas import EvaluationRequest
from app.models.sources import registered_asset
from app.training.repository import get_task
from app.evaluation.snapshot import validate_source
from app.evaluation.evidence import read_evidence
from app.evaluation.repository import evaluation_dir


def create(db: Session, request: EvaluationRequest, key: str | None) -> dict:
    config = request.model_dump(mode="json")
    with db.begin():
        if key:
            db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended("evaluation:" + key, 0))))
            previous = db.scalar(select(EvaluationRun).where(EvaluationRun.idempotency_key == key))
            if previous:
                if previous.config != config:
                    raise Conflict("幂等键已用于其他评估配置")
                return response(previous)
        version, task, _, _ = registered_asset(db, "version:" + str(request.versionId))
        if version.lifecycle == "archived":
            raise Conflict("归档模型不能创建新的评估")
        if task.config["task"] not in ("detect", "segment", "obb"):
            raise ValueError("独立评估仅支持 Detect/Segment/OBB")
        source = get_task(db, str(request.sourceTaskId)) if request.sourceTaskId else task
        split = "val" if request.purpose == "diagnostic" else "test"
        validate_source(task, source, split)
        row = EvaluationRun(version_id=version.id, idempotency_key=key, config=config)
        db.add(row)
        db.flush()
        return response(row)


def status(db: Session, run_id: str) -> dict:
    return response(get_run(db, run_id))


def listing(db: Session, version_id: str | None) -> dict:
    query = select(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(100)
    if version_id:
        query = query.where(EvaluationRun.version_id == version_id)
    return {"items": [response(row) for row in db.scalars(query)]}


def cancel(db: Session, run_id: str) -> dict:
    with db.begin():
        row = get_run(db, run_id, True)
        if row.status in ("queued", "running"):
            row.cancel_requested = True
            if row.status == "queued":
                row.status, row.phase = "canceled", "canceled"
                row.finished_at = datetime.now(timezone.utc)
        return response(row)


def logs(db: Session, run_id: str, after: int) -> dict:
    row = get_run(db, run_id)
    items = [item for item in row.logs if item["sequence"] > after]
    return {"items": items, "nextSequence": items[-1]["sequence"] if items else after}


def images(db: Session, run_id: str, page: int = 1, page_size: int = 30) -> dict:
    row = get_run(db, run_id)
    items = (row.report or {}).get("perImage", [])
    start = (page - 1) * page_size
    return {"items": items[start:start + page_size], "total": len(items), "page": page, "pageSize": page_size}


def image_detail(db: Session, run_id: str, image_id: str) -> dict:
    row = get_run(db, run_id)
    if row.status != "succeeded":
        raise Conflict("评估尚未完成，无法读取逐图证据")
    return read_evidence(evaluation_dir(row.id), image_id, (row.report or {}).get("perImage", []))


def image_content(db: Session, run_id: str, image_id: str, thumbnail=False):
    from app.evaluation.images import frozen_image
    row = get_run(db, run_id)
    if row.status != "succeeded" or not row.report:
        raise Conflict("评估尚未完成，无法读取冻结图片")
    return frozen_image(evaluation_dir(row.id), row.report["snapshot"]["digest"], image_id, thumbnail)


TOOLS = {"evaluation.start": create, "evaluation.summary": status, "evaluation.list": listing,
         "evaluation.cancel": cancel, "evaluation.logs": logs,
         "evaluation.images": images, "evaluation.image_detail": image_detail,
         "evaluation.image_content": image_content}
