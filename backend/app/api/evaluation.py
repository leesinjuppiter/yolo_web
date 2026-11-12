from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.evaluation.schemas import EvaluationRequest
from app.evaluation.service import TOOLS

router = APIRouter(prefix="/api/evaluations", tags=["evaluation"])
Database = Annotated[Session, Depends(get_db)]


@router.post("", status_code=202)
def create(request: EvaluationRequest, db: Database,
           key: Annotated[str | None, Header(alias="Idempotency-Key", min_length=1, max_length=120)] = None):
    return TOOLS["evaluation.start"](db, request, key)


@router.get("")
def listing(db: Database, versionId: UUID | None = None):
    return TOOLS["evaluation.list"](db, str(versionId) if versionId else None)


@router.get("/{run_id}")
def status(run_id: UUID, db: Database):
    return TOOLS["evaluation.summary"](db, str(run_id))


@router.get("/{run_id}/logs")
def logs(run_id: UUID, db: Database, after_sequence: Annotated[int, Query(ge=0)] = 0):
    return TOOLS["evaluation.logs"](db, str(run_id), after_sequence)


@router.post("/{run_id}/cancel")
def cancel(run_id: UUID, db: Database):
    return TOOLS["evaluation.cancel"](db, str(run_id))


@router.get("/{run_id}/images")
def images(run_id: UUID, db: Database, page: Annotated[int, Query(ge=1)] = 1,
           page_size: Annotated[int, Query(ge=1, le=100)] = 30):
    return TOOLS["evaluation.images"](db, str(run_id), page, page_size)


@router.get("/{run_id}/images/{image_id}")
def image_detail(run_id: UUID, image_id: str, db: Database):
    return TOOLS["evaluation.image_detail"](db, str(run_id), image_id)


@router.get("/{run_id}/images/{image_id}/content")
def image_content(run_id: UUID, image_id: str, db: Database):
    return FileResponse(TOOLS["evaluation.image_content"](db, str(run_id), image_id),
                        headers={"Cache-Control": "private, max-age=86400"})


@router.get("/{run_id}/images/{image_id}/thumbnail")
def image_thumbnail(run_id: UUID, image_id: str, db: Database):
    return FileResponse(TOOLS["evaluation.image_content"](db, str(run_id), image_id, True),
                        media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
