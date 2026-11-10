from sqlalchemy.orm import Session

from app.dataset import repository
from app.dataset.analysis.reporting import read_snapshot, refresh_report
from app.quality.report import duplicate_report, quality_report
from app.quality.review import load_review_decisions
from app.validation.report import DatasetReport, validate_dataset

from .coco import import_coco_archive, import_coco_directory
from .local_directory import list_local_directories
from .service import export_yolo, import_yolo, import_yolo_directory


def dataset_validation(db: Session, dataset_id: str) -> DatasetReport:
    return validate_dataset(repository.get_dataset(db, dataset_id))


def dataset_quality(db: Session, dataset_id: str) -> DatasetReport:
    dataset = repository.get_dataset(db, dataset_id, include_images=False)
    return quality_report(dataset, *repository.quality_counts(db, dataset_id))


def dataset_duplicates(db: Session, dataset_id: str) -> DatasetReport:
    repository.get_dataset(db, dataset_id, include_images=False)
    sources = repository.list_image_sources(db, dataset_id)
    return duplicate_report([(image.name, image.storage_path) for image in sources],
                            image_ids=[image.id for image in sources], reviews=load_review_decisions(db, dataset_id))


EXCHANGE_TOOLS = {
    "dataset.validate": dataset_validation,
    "dataset.quality_report": dataset_quality,
    "dataset.duplicates": dataset_duplicates,
    "dataset.report_snapshot": read_snapshot,
    "dataset.refresh_report": refresh_report,
    "annotation.export_yolo": export_yolo,
    "dataset.exchange.import_yolo": import_yolo,
    "dataset.exchange.browse_local_directories": list_local_directories,
    "dataset.exchange.import_yolo_directory": import_yolo_directory,
    "dataset.exchange.import_coco": import_coco_archive,
    "dataset.exchange.import_coco_directory": import_coco_directory,
}
