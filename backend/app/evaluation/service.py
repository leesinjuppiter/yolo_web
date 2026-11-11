from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dataset.repository import Conflict
from app.evaluation.models import EvaluationRun
from app.evaluation.repository import get_run, response
from app.evaluation.schemas import EvaluationRequest
from app.models.sources import registered_asset


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
        if task.config["task"] not in ("detect", "obb"):
            raise ValueError("首版独立评估仅支持 Detect/OBB")
        if not (task.snapshot or {}).get("split_counts", {}).get("test"):
            raise ValueError("模型来源训练快照没有 test 分集")
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


TOOLS = {"evaluation.start": create, "evaluation.summary": status, "evaluation.list": listing,
         "evaluation.cancel": cancel, "evaluation.logs": logs}
