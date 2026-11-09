from sqlalchemy.orm import Session

from app.dataset import repository
from app.quality.report import duplicate_report, quality_report
from app.validation.report import DatasetReport, validate_dataset

from .service import export_yolo, import_yolo


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
}
