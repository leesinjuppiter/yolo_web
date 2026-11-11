from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import data_dir
from app.dataset.repository import NotFound
from app.evaluation.models import EvaluationRun


def evaluation_dir(run_id: str) -> Path:
    return data_dir() / "evaluations" / str(UUID(run_id))


def get_run(db: Session, run_id: str, lock: bool = False) -> EvaluationRun:
    row = db.get(EvaluationRun, run_id, with_for_update=lock)
    if row is None:
        raise NotFound("评估任务不存在")
    return row


def response(row: EvaluationRun) -> dict:
    return {"id": row.id, "versionId": row.version_id, "status": row.status, "phase": row.phase,
            "config": row.config, "report": row.report, "error": row.error,
            "createdAt": row.created_at, "startedAt": row.started_at, "finishedAt": row.finished_at}


def log(row: EvaluationRun, message: str, level: str = "info"):
    row.logs = [*row.logs, {"sequence": (row.logs[-1]["sequence"] if row.logs else 0) + 1, "level": level,
                          "message": message, "time": datetime.now(timezone.utc).isoformat()}][-1000:]
