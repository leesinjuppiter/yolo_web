from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.evaluation.schemas import CompareRequest, MetadataRequest
from app.models.registry import TOOLS

router = APIRouter(prefix="/api/models", tags=["models"])
Database = Annotated[Session, Depends(get_db)]


@router.get("")
def listing(db: Database, query: Annotated[str, Query(max_length=120)] = "",
            task: Literal["detect", "segment", "obb", "classify"] | None = None,
            lifecycle: Literal["candidate", "archived"] | None = None,
            page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 10):
    return TOOLS["model.list"](db, query, task, lifecycle, page, page_size)


@router.post("/compare")
def compare(request: CompareRequest, db: Database):
    return TOOLS["model.compare"](db, request)


@router.get("/{version_id}")
def detail(version_id: UUID, db: Database):
    return TOOLS["model.detail"](db, str(version_id))


@router.patch("/{version_id}")
def update(version_id: UUID, request: MetadataRequest, db: Database):
    return TOOLS["model.update_metadata"](db, str(version_id), request)


@router.post("/{version_id}/archive")
def archive(version_id: UUID, db: Database):
    return TOOLS["model.lifecycle"](db, str(version_id), True)


@router.post("/{version_id}/restore")
def restore(version_id: UUID, db: Database):
    return TOOLS["model.lifecycle"](db, str(version_id), False)
