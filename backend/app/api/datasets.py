from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import StringConstraints
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.storage import MAX_IMAGE_BYTES
from app.dataset import schemas, service
from app.dataset.tools import TOOLS
from app.quality.review_models import ReviewDecision

router = APIRouter(prefix="/api/datasets", tags=["datasets"])
Database = Annotated[Session, Depends(get_db)]
ImageDigest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class SimilarityReview(schemas.RequestModel):
    image_id: UUID
    related_image_id: UUID
    image_sha256: ImageDigest
    related_image_sha256: ImageDigest
    decision: ReviewDecision


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


@router.post("/{dataset_id}/similarity-reviews", status_code=204)
def review_similarity(dataset_id: UUID, payload: SimilarityReview, db: Database):
    TOOLS["dataset.review_similarity"](
        db, str(dataset_id), str(payload.image_id), str(payload.related_image_id),
        payload.image_sha256, payload.related_image_sha256, payload.decision,
    )
    return Response(status_code=204)


@router.get("/{dataset_id}/excluded-images", response_model=list[schemas.ImageResponse])
def list_excluded_images(dataset_id: UUID, db: Database):
    return TOOLS["dataset.list_excluded_images"](db, str(dataset_id))


@router.post("/{dataset_id}/excluded-images/{image_id}/restore", response_model=schemas.ImageResponse)
def restore_image(dataset_id: UUID, image_id: UUID, db: Database):
    return TOOLS["dataset.restore_excluded_image"](db, str(dataset_id), str(image_id))


@router.patch("/{dataset_id}/splits", response_model=schemas.DatasetResponse)
def update_splits(dataset_id: UUID, request: schemas.SplitUpdate, db: Database):
    return service.update_splits(db, str(dataset_id), request)


@router.patch("/{dataset_id}/classes/{class_id}", response_model=schemas.ClassResponse)
def update_class(dataset_id: UUID, class_id: UUID, request: schemas.ClassUpdate, db: Database):
    return service.update_class(db, str(dataset_id), str(class_id), request)


@router.put("/{dataset_id}/images/{image_id}/annotations",
            response_model=schemas.DatasetResponse | schemas.AnnotationSaveResponse)
def save_annotations(dataset_id: UUID, image_id: UUID, request: schemas.AnnotationSave, db: Database, compact: bool = False):
    return service.save_annotations(db, str(dataset_id), str(image_id), request, compact=compact)


@router.get("/{dataset_id}/images/{image_id}/content", response_class=FileResponse)
def image_content(dataset_id: UUID, image_id: UUID, db: Database):
    return FileResponse(service.image_path(db, str(dataset_id), str(image_id)))
