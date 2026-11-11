from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.model_exports.schemas import ExportRequest
from app.model_exports.service import TOOLS

router = APIRouter(prefix="/api/exports", tags=["model-exports"])
Database = Annotated[Session, Depends(get_db)]
Key = Annotated[str | None, Header(alias="Idempotency-Key", min_length=1, max_length=120)]


@router.get("")
def overview(db: Database, page: Annotated[int, Query(ge=1)] = 1,
             page_size: Annotated[int, Query(ge=1, le=100)] = 20):
    return TOOLS["model.export_list"](db, page, page_size)


@router.post("", status_code=202)
def create(request: ExportRequest, db: Database, key: Key = None):
    return TOOLS["model.export_onnx"](db, request, key)


@router.get("/{task_id}")
def detail(task_id: UUID, db: Database):
    return TOOLS["model.export_status"](db, str(task_id))


@router.get("/{task_id}/logs")
def logs(task_id: UUID, db: Database, after_sequence: Annotated[int, Query(ge=0)] = 0):
    return TOOLS["model.export_logs"](db, str(task_id), after_sequence)


@router.post("/{task_id}/cancel")
def cancel(task_id: UUID, db: Database):
    return TOOLS["model.export_cancel"](db, str(task_id))


@router.get("/{task_id}/download", response_class=FileResponse)
def download(task_id: UUID, db: Database):
    return FileResponse(TOOLS["model.export_download"](db, str(task_id)), filename=f"{task_id}.onnx")
