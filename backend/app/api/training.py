from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.training.schemas import Sort, Status, TrainingConfig, TrainingType
from app.training.tools import TOOLS

router = APIRouter(prefix="/api/training", tags=["training"])
Database = Annotated[Session, Depends(get_db)]
After = Annotated[int, Query(ge=0, le=9223372036854775807)]
Limit = Annotated[int, Query(ge=1, le=1000)]


@router.get("/options")
def options():
    return TOOLS["training.options"]()


@router.post("/preflight")
def preflight(config: TrainingConfig, db: Database):
    return TOOLS["training.preflight"](db, config)


@router.get("")
def overview(db: Database, status: Status | None = None, task: TrainingType | None = None,
             architecture: Annotated[str | None, Query(max_length=40)] = None,
             query: Annotated[str, Query(max_length=120)] = "", sort: Sort = "newest",
             page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 6):
    return TOOLS["training.list"](db, status=status, task_type=task, architecture=architecture,
                                  query=query.strip(), sort=sort, page=page, page_size=page_size)


@router.post("", status_code=202)
def create(config: TrainingConfig, db: Database,
           key: Annotated[str | None, Header(alias="Idempotency-Key", min_length=1, max_length=120)] = None):
    return TOOLS["training.start"](db, config, key)


@router.get("/{task_id}")
def status(task_id: UUID, db: Database):
    return TOOLS["training.status"](db, str(task_id))


@router.post("/{task_id}/cancel")
def cancel(task_id: UUID, db: Database):
    return TOOLS["training.cancel"](db, str(task_id))


@router.get("/{task_id}/logs")
def logs(task_id: UUID, db: Database, after_sequence: After = 0, limit: Limit = 200):
    return TOOLS["training.logs"](db, str(task_id), after_sequence, limit)


@router.get("/{task_id}/metrics")
def metrics(task_id: UUID, db: Database, after_sequence: After = 0, limit: Limit = 200):
    return TOOLS["training.metrics"](db, str(task_id), after_sequence, limit)


@router.get("/{task_id}/result")
def result(task_id: UUID, db: Database):
    return TOOLS["training.latest_result"](db, str(task_id))


@router.get("/{task_id}/failure")
def failure(task_id: UUID, db: Database):
    return TOOLS["training.diagnose_failure"](db, str(task_id))


@router.post("/{task_id}/model-version")
def register_version(task_id: UUID, db: Database):
    return TOOLS["model.register_training_version"](db, str(task_id))


@router.get("/{task_id}/artifacts/{artifact_id}")
def artifact(task_id: UUID, artifact_id: str, db: Database):
    item, path = TOOLS["training.download_artifact"](db, str(task_id), artifact_id)
    return FileResponse(path, filename=item["name"],
                        content_disposition_type="inline" if item["kind"] == "preview" else "attachment")

