from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
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
