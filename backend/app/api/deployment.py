from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deployment.service import TOOLS
from app.model_exports.schemas import PackageRequest

router = APIRouter(prefix="/api/deployment-packages", tags=["deployment-packages"])
Database = Annotated[Session, Depends(get_db)]


@router.get("")
def overview(db: Database, page: Annotated[int, Query(ge=1)] = 1,
             page_size: Annotated[int, Query(ge=1, le=100)] = 20):
    return TOOLS["deployment.package_list"](db, page, page_size)


@router.post("", status_code=202)
def create(request: PackageRequest, db: Database,
           key: Annotated[str | None, Header(alias="Idempotency-Key", min_length=1, max_length=120)] = None):
    return TOOLS["deployment.package_build"](db, request, key)


@router.get("/{package_id}")
def detail(package_id: UUID, db: Database):
    return TOOLS["deployment.package_detail"](db, str(package_id))


@router.get("/{package_id}/download", response_class=FileResponse)
def download(package_id: UUID, db: Database):
    return FileResponse(TOOLS["deployment.package_download"](db, str(package_id)),
                        filename=f"deployment-{package_id}.zip")
