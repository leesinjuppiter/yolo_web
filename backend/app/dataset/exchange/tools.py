from sqlalchemy.orm import Session

from app.dataset import repository
from app.quality.report import duplicate_report, quality_report
from app.validation.report import DatasetReport, validate_dataset

from .coco import import_coco_archive, import_coco_directory
from .local_directory import list_local_directories
from .service import export_yolo, import_yolo, import_yolo_directory


def dataset_validation(db: Session, dataset_id: str) -> DatasetReport:
    return validate_dataset(repository.get_dataset(db, dataset_id))


def dataset_quality(db: Session, dataset_id: str) -> DatasetReport:
    return quality_report(repository.get_dataset(db, dataset_id))


def dataset_duplicates(db: Session, dataset_id: str) -> DatasetReport:
    return duplicate_report(repository.get_dataset(db, dataset_id))


EXCHANGE_TOOLS = {
    "dataset.validate": dataset_validation,
    "dataset.quality_report": dataset_quality,
    "dataset.duplicates": dataset_duplicates,
    "annotation.export_yolo": export_yolo,
    "dataset.exchange.import_yolo": import_yolo,
    "dataset.exchange.browse_local_directories": list_local_directories,
    "dataset.exchange.import_yolo_directory": import_yolo_directory,
    "dataset.exchange.import_coco": import_coco_archive,
    "dataset.exchange.import_coco_directory": import_coco_directory,
}
