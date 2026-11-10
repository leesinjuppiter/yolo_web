from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.core.database import get_db
from app.dataset import schemas
from app.dataset.analysis.queue import ReportKind
from app.dataset.analysis.reporting import ReportSnapshot
from app.dataset.exchange.coco import CocoImportResponse, CocoTask
from app.dataset.exchange.service import stream_archive
from app.dataset.exchange.tools import EXCHANGE_TOOLS
from app.validation.report import DatasetReport

router = APIRouter(prefix="/api/datasets", tags=["dataset exchange"])
Database = Annotated[Session, Depends(get_db)]


class DirectoryImport(BaseModel):
    path: str = Field(min_length=1, max_length=2048)
    task_type: schemas.TaskType


class CocoDirectoryImport(DirectoryImport):
    task_type: CocoTask
    skip_invalid: bool = False


class ReportRefresh(schemas.RequestModel):
    force: bool = False


def _local_workbench(request: Request) -> None:
    if (request.client is None or request.client.host not in {"127.0.0.1", "::1"}
            or request.url.hostname not in {"localhost", "127.0.0.1", "::1"}):
        raise HTTPException(status_code=403, detail="本地目录功能仅在本机工作台可用")


@router.post("/import/yolo", response_model=schemas.DatasetResponse, status_code=201)
def import_archive(file: Annotated[UploadFile, File()], task_type: Annotated[schemas.TaskType, Form()],
                   db: Database):
    return EXCHANGE_TOOLS["dataset.exchange.import_yolo"](
        db, file.file, file.filename or "YOLO 数据集.zip", task_type,
    )


@router.get("/import/directories", dependencies=[Depends(_local_workbench)])
def browse_directories(path: str | None = None):
    return EXCHANGE_TOOLS["dataset.exchange.browse_local_directories"](path)


@router.post("/import/coco", response_model=CocoImportResponse, status_code=201)
def import_coco_archive(file: Annotated[UploadFile, File()], task_type: Annotated[CocoTask, Form()], db: Database,
                        skip_invalid: Annotated[bool, Form()] = False):
    return EXCHANGE_TOOLS["dataset.exchange.import_coco"](
        db, file.file, file.filename or "COCO 数据集.zip", task_type, skip_invalid=skip_invalid,
    )


@router.post("/import/coco-directory", response_model=CocoImportResponse, status_code=201,
             dependencies=[Depends(_local_workbench)])
def import_coco_directory(payload: CocoDirectoryImport, db: Database):
    return EXCHANGE_TOOLS["dataset.exchange.import_coco_directory"](
        db, payload.path, payload.task_type, skip_invalid=payload.skip_invalid,
    )


@router.post("/import/yolo-directory", response_model=schemas.DatasetResponse, status_code=201,
             dependencies=[Depends(_local_workbench)])
def import_directory(payload: DirectoryImport, db: Database):
    return EXCHANGE_TOOLS["dataset.exchange.import_yolo_directory"](db, payload.path, payload.task_type)


@router.get("/{dataset_id}/export/yolo", response_class=StreamingResponse)
def export_archive(dataset_id: UUID, db: Database, include_images: bool = True, include_negative: bool = True):
    output = EXCHANGE_TOOLS["annotation.export_yolo"](db, str(dataset_id), include_images, include_negative)
    return StreamingResponse(
        stream_archive(output), media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="dataset-yolo.zip"'},
        background=BackgroundTask(output.close),
    )


@router.get("/{dataset_id}/reports/{kind}", response_model=DatasetReport)
def report(dataset_id: UUID, kind: ReportKind, db: Database):
    names = {"validate": "dataset.validate", "duplicates": "dataset.duplicates", "quality": "dataset.quality_report"}
    return EXCHANGE_TOOLS[names[kind]](db, str(dataset_id))


@router.get("/{dataset_id}/reports/{kind}/snapshot", response_model=ReportSnapshot)
def report_snapshot(dataset_id: UUID, kind: ReportKind, db: Database):
    return EXCHANGE_TOOLS["dataset.report_snapshot"](db, str(dataset_id), kind)


@router.post("/{dataset_id}/reports/{kind}/refresh", response_model=ReportSnapshot, status_code=202)
def refresh_report(dataset_id: UUID, kind: ReportKind, payload: ReportRefresh, db: Database):
    return EXCHANGE_TOOLS["dataset.refresh_report"](db, str(dataset_id), kind, force=payload.force)
