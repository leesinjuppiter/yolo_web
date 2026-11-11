"""Resolve registered model assets without trusting client-supplied file paths."""

from hashlib import file_digest
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import data_dir
from app.dataset.repository import Conflict, NotFound
from app.models.training_versions import ModelVersion
from app.training.catalog import ModelOption
from app.training.models import TrainingTask


def _rows(db: Session):
    return db.execute(select(ModelVersion, TrainingTask).join(
        TrainingTask, TrainingTask.id == ModelVersion.task_id,
    ).order_by(ModelVersion.number.desc())).all()


def model_options(db: Session) -> list[dict]:
    return [{
        "id": f"version:{version.id}", "name": f"{task.config['name']} · v{version.number}",
        "architecture": task.architecture, "task": task.config["task"], "pretrained": True,
        "sourceType": "model_version", "versionId": version.id, "sourceTaskId": task.id,
    } for version, task in _rows(db)]


def registered_asset(db: Session, model_id: str) -> tuple[ModelVersion, TrainingTask, dict, Path]:
    try:
        version_id = str(UUID(model_id.removeprefix("version:")))
    except ValueError as exc:
        raise ValueError("模型版本 ID 不合法") from exc
    version = db.get(ModelVersion, version_id)
    if version is None:
        raise NotFound("模型版本不存在")
    task = db.get(TrainingTask, version.task_id)
    artifact = next((item for item in task.artifacts if item["id"] == version.artifact_id), None)
    if artifact is None:
        raise Conflict("模型版本对应的训练产物不存在")
    root = (data_dir() / "training" / task.id).resolve()
    path = (root / artifact["path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise Conflict("模型版本权重文件不存在")
    with path.open("rb") as source:
        if file_digest(source, "sha256").hexdigest() != version.sha256:
            raise Conflict("模型版本权重校验失败，文件已发生变化")
    return version, task, artifact, path


def resolve_version_model(db: Session, model_id: str) -> ModelOption:
    version, task, _, path = registered_asset(db, model_id)
    return ModelOption(
        model_id, f"{task.config['name']} · v{version.number}", task.architecture,
        task.config["task"], str(path), True, source_type="model_version", sha256=version.sha256,
    )


TOOLS = {"model.training_options": model_options, "model.resolve_training_source": resolve_version_model}
