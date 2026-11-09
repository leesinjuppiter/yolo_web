from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.core.database import get_db
from app.dataset import schemas
from app.dataset.exchange.service import stream_archive
from app.dataset.exchange.tools import EXCHANGE_TOOLS
from app.validation.report import DatasetReport

router = APIRouter(prefix="/api/datasets", tags=["dataset exchange"])
Database = Annotated[Session, Depends(get_db)]


@router.post("/import/yolo", response_model=schemas.DatasetResponse, status_code=201)
def import_archive(file: Annotated[UploadFile, File()], task_type: Annotated[schemas.TaskType, Form()],
                   db: Database):
    return EXCHANGE_TOOLS["dataset.exchange.import_yolo"](
        db, file.file, file.filename or "YOLO 数据集.zip", task_type,
    )


@router.get("/{dataset_id}/export/yolo", response_class=StreamingResponse)
def export_archive(dataset_id: UUID, db: Database, include_images: bool = True, include_negative: bool = True):
    output = EXCHANGE_TOOLS["annotation.export_yolo"](db, str(dataset_id), include_images, include_negative)
    return StreamingResponse(
        stream_archive(output), media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="dataset-yolo.zip"'},
        background=BackgroundTask(output.close),
    )


@router.get("/{dataset_id}/reports/{kind}", response_model=DatasetReport)
def report(dataset_id: UUID, kind: Literal["validate", "duplicates", "quality"], db: Database):
    names = {"validate": "dataset.validate", "duplicates": "dataset.duplicates", "quality": "dataset.quality_report"}
    return EXCHANGE_TOOLS[names[kind]](db, str(dataset_id))
