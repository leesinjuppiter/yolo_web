from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.storage import MAX_IMAGE_BYTES
from app.dataset import schemas, service

router = APIRouter(prefix="/api/datasets", tags=["datasets"])
Database = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[schemas.DatasetResponse])
def list_datasets(db: Database):
    return service.list_datasets(db)


@router.post("", response_model=schemas.DatasetResponse, status_code=201)
def create_dataset(request: schemas.DatasetCreate, db: Database):
    return service.create_dataset(db, request)


@router.get("/{dataset_id}", response_model=schemas.DatasetResponse)
def dataset_summary(dataset_id: UUID, db: Database):
    return service.dataset_summary(db, str(dataset_id))


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: UUID, db: Database):
    service.delete_dataset(db, str(dataset_id))
    return Response(status_code=204)


@router.post("/{dataset_id}/images", response_model=schemas.DatasetResponse)
def upload_images(
    dataset_id: UUID,
    db: Database,
    files: Annotated[list[UploadFile], File()],
    split: Annotated[schemas.Split | None, Form()] = None,
):
    if len(files) > 200:
        raise ValueError("每批最多添加 200 张图片")
    images = ((file.filename or "", file.file.read(MAX_IMAGE_BYTES + 1)) for file in files)
    return service.upload_images(db, str(dataset_id), split, images)


@router.delete("/{dataset_id}/images/{image_id}", status_code=204)
def delete_image(dataset_id: UUID, image_id: UUID, db: Database):
    service.delete_image(db, str(dataset_id), str(image_id))
    return Response(status_code=204)


@router.patch("/{dataset_id}/splits", response_model=schemas.DatasetResponse)
def update_splits(dataset_id: UUID, request: schemas.SplitUpdate, db: Database):
    return service.update_splits(db, str(dataset_id), request)


@router.patch("/{dataset_id}/classes/{class_id}", response_model=schemas.ClassResponse)
def update_class(dataset_id: UUID, class_id: UUID, request: schemas.ClassUpdate, db: Database):
    return service.update_class(db, str(dataset_id), str(class_id), request)


@router.put("/{dataset_id}/images/{image_id}/annotations", response_model=schemas.DatasetResponse)
def save_annotations(dataset_id: UUID, image_id: UUID, request: schemas.AnnotationSave, db: Database):
    return service.save_annotations(db, str(dataset_id), str(image_id), request)


@router.get("/{dataset_id}/images/{image_id}/content", response_class=FileResponse)
def image_content(dataset_id: UUID, image_id: UUID, db: Database):
    return FileResponse(service.image_path(db, str(dataset_id), str(image_id)))
