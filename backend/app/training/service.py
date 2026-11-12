from datetime import datetime, timezone
from math import isfinite

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dataset.repository import Conflict, NotFound
from app.models.training_versions import ModelVersion
from app.models.sources import model_options, resolve_version_model
from app.training import catalog, dataset_options, repository, resume as resume_service
from app.training.artifact_archive import build_archive
from app.training.devices import available_devices, capabilities, device_description, validate_device
from app.training.errors import PreflightError
from app.training.models import TrainingMetric, TrainingTask
from app.training.resources import resource_status
from app.training.runtime import public_runtime
from app.training.schemas import ACTIVE, TERMINAL, TrainingConfig
from app.training.snapshot import inspect_dataset
from app.training.resume_schemas import ResumeRequest


def _digest(task: TrainingTask) -> str | None:
    return (task.snapshot or {}).get("digest")


def _model_version(task: TrainingTask, version: ModelVersion) -> dict:
    return {
        "id": version.id, "version": f"v{version.number}", "taskId": task.id, "taskType": task.config["task"],
        "datasetId": task.dataset_id, "datasetName": task.dataset_name, "snapshotDigest": _digest(task),
        "artifactId": version.artifact_id, "sha256": version.sha256, "createdAt": version.created_at,
        "validationStatus": "unverified",
    }


def _artifact_url(task: TrainingTask, artifact_id: str) -> str:
    return f"/api/training/{task.id}/artifacts/{artifact_id}"


def _public_artifact(task: TrainingTask, item: dict) -> dict:
    return {
        "id": item["id"], "name": item["name"], "kind": item["kind"], "sha256": item["sha256"],
        "sizeBytes": item["sizeBytes"], "url": _artifact_url(task, item["id"]),
    }


def task_response(task: TrainingTask, version: ModelVersion | None = None) -> dict:
    now = datetime.now(timezone.utc)
    elapsed = (task.finished_at or now) - task.started_at if task.started_at else None
    summary = task.failure.get("summary") if task.failure else None
    return {
        "id": task.id, "config": task.config, "datasetName": task.dataset_name,
        "datasetImageCount": task.dataset_image_count, "datasetClassCount": task.dataset_class_count,
        "modelName": task.model_name, "architecture": task.architecture, "status": task.status,
        "phase": task.phase, "cancelRequested": task.cancel_requested,
        "createdAt": task.created_at, "startedAt": task.started_at, "finishedAt": task.finished_at,
        "heartbeatAt": task.heartbeat_at, "elapsedSeconds": max(0, elapsed.total_seconds()) if elapsed is not None else None,
        "epoch": task.epoch, "metrics": task.metrics, "error": summary, "failure": task.failure,
        "actions": ["cancel"] if task.status in ACTIVE and not task.cancel_requested else [],
        "artifacts": [_public_artifact(task, item) for item in task.artifacts],
        "previews": [
            {"id": item["id"], "name": item["name"], "url": _artifact_url(task, item["artifactId"]),
             "groundTruthUrl": _artifact_url(task, item["groundTruthArtifactId"]),
             "width": item.get("width"), "height": item.get("height")}
            for item in task.previews
        ],
        "device": task.environment.get("device")
        if isinstance((task.environment or {}).get("device"), dict) else device_description(task.config["deviceId"]),
        "snapshotDigest": _digest(task),
        "modelVersion": _model_version(task, version) if version else None,
        "parentModelVersionId": task.parent_model_version_id,
        "resumeFromTaskId": task.resume_from_task_id,
        "resume": resume_service.availability(task),
    }


def options(db: Session) -> dict:
    result = catalog.options()
    result["models"].extend(model_options(db))
    return result


def _model_for(db: Session, config: TrainingConfig) -> catalog.ModelOption:
    model = (resolve_version_model(db, config.modelId) if config.modelId.startswith("version:")
             else catalog.resolve_model(config.modelId))
    catalog.validate_model_config(config, model)
    validate_device(config.deviceId)
    return model


def preflight(db: Session, config: TrainingConfig) -> dict:
    _model_for(db, config)
    return inspect_dataset(db, str(config.datasetId), config.task)


def create(db: Session, config: TrainingConfig, key: str | None) -> dict:
    config_json = config.model_dump(mode="json")
    with db.begin():
        if key:
            db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"training:{key}", 0))))
            previous = db.scalar(select(TrainingTask).where(TrainingTask.idempotency_key == key))
            if previous is not None:
                if previous.config != config_json:
                    raise Conflict("该请求已提交，请重新填写任务后再提交")
                return task_response(previous, repository.get_model_version(db, previous.id))
        repository.reserve_task_name(db, config.name)
        model = _model_for(db, config)
        report = inspect_dataset(db, str(config.datasetId), config.task)
        if not report.get("datasetName"):
            raise NotFound("未找到数据集")
        if report["errors"]:
            raise PreflightError(report["errors"])
        task = TrainingTask(
            idempotency_key=key, dataset_id=str(config.datasetId), dataset_name=report["datasetName"],
            dataset_image_count=report["imageCount"], dataset_class_count=report["classCount"],
            dataset_revision=report.get("revision"), config=config_json, model_name=model.name,
            architecture=model.architecture, status="queued", phase="queued",
            parent_model_version_id=config.modelId.removeprefix("version:")
            if config.modelId.startswith("version:") else None,
        )
        db.add(task)
        db.flush()
        return task_response(task)


def overview(db: Session, **filters) -> dict:
    rows, summary = repository.training_overview(db, **filters)
    worker = capabilities()
    return {**summary, "tasks": [task_response(task, version) for task, version in rows],
            "devices": worker["devices"], "workerStatus": worker["workerStatus"], "engine": catalog.engine_name(),
            "workerAvailable": repository.worker_available(db)}


def status(db: Session, task_id: str) -> dict:
    task = repository.get_task(db, task_id)
    response = task_response(task, repository.get_model_version(db, task_id))
    if runtime := public_runtime(task.environment):
        response["runtime"] = runtime
    if (eta := _eta_seconds(db, task)) is not None:
        response["etaSeconds"] = eta
    return response


def _eta_seconds(db: Session, task: TrainingTask) -> float | None:
    if task.status != "running" or task.phase != "training" or task.cancel_requested or task.epoch < 2:
        return None
    if not task.heartbeat_at or (datetime.now(timezone.utc) - task.heartbeat_at).total_seconds() > 10:
        return None
    timings = repository.recent_epoch_timings(db, task.id, task.epoch)
    if len(timings) < 2:
        return None
    latest, latest_time = timings[0]
    first, first_time = timings[-1]
    remaining = task.config["epochs"] - latest
    if remaining > 0 and latest > first and latest_time > first_time:
        estimate = remaining * (latest_time - first_time) / (latest - first)
        if isfinite(estimate):
            return estimate
    return None


def resources(db: Session, task_id: str) -> dict:
    return resource_status(repository.get_task(db, task_id))


def cancel(db: Session, task_id: str) -> dict:
    with db.begin():
        task = repository.get_task(db, task_id, lock=True)
        if task.status in TERMINAL:
            if task.status == "canceled":
                return task_response(task)
            raise Conflict("训练任务已结束")
        task.cancel_requested = True
        if task.status in ("created", "queued") and task.worker_token is None:
            task.status, task.phase = "canceled", "canceled"
            task.finished_at = datetime.now(timezone.utc)
        return task_response(task)


def delete(db: Session, task_id: str) -> None:
    with db.begin():
        task = repository.get_task(db, task_id, lock=True)
        if task.status not in TERMINAL:
            raise Conflict("请先取消或结束训练任务，再删除记录")
        if repository.get_model_version(db, task_id) is not None:
            raise Conflict("该训练任务已注册模型版本，需保留来源记录")
        if db.scalar(select(TrainingTask.id).where(TrainingTask.resume_from_task_id == task_id).limit(1)):
            raise Conflict("该任务是恢复训练的来源，需保留来源记录")
        db.delete(task)


def logs(db: Session, task_id: str, after: int, limit: int) -> list[dict]:
    repository.require_task(db, task_id)
    rows = db.execute(repository.log_query(task_id, after).limit(limit))
    return [{"sequence": row.sequence, "time": row.time, "level": row.level, "message": row.message}
            for row in rows]


def metrics(db: Session, task_id: str, after: int, limit: int) -> list[dict]:
    repository.require_task(db, task_id)
    rows = db.scalars(select(TrainingMetric).where(TrainingMetric.task_id == task_id, TrainingMetric.sequence > after)
                      .order_by(TrainingMetric.sequence).limit(limit))
    return [{"sequence": row.sequence, "epoch": row.epoch, "values": row.values, "step": row.step,
             "elapsedSeconds": row.elapsed_seconds} for row in rows]


def latest_result(db: Session, task_id: str) -> dict:
    task = repository.get_task(db, task_id)
    return {"taskId": task.id, "status": task.status, "metrics": task.metrics,
            "snapshot": _digest(task), "environment": task.environment,
            "artifacts": [_public_artifact(task, item) for item in task.artifacts]}


def diagnose_failure(db: Session, task_id: str) -> dict | None:
    return repository.get_task(db, task_id).failure


def register_version(db: Session, task_id: str) -> dict:
    with db.begin():
        task = repository.get_task(db, task_id, lock=True)
        existing = repository.get_model_version(db, task_id)
        if existing is not None:
            return _model_version(task, existing)
        if task.status != "succeeded":
            raise Conflict("训练成功后才能注册模型版本")
        artifact = next((item for item in task.artifacts
                         if item["kind"] == "checkpoint" and item["name"] == "best.pt"), None)
        if artifact is None or not _digest(task):
            raise Conflict("缺少训练快照或最优权重，无法注册模型版本")
        repository.verified_artifact_file(task, artifact["id"])
        digest = artifact["sha256"]
        version = ModelVersion(task_id=task_id, artifact_id=artifact["id"], sha256=digest)
        db.add(version)
        db.flush()
        return _model_version(task, version)


def download(db: Session, task_id: str, artifact_id: str):
    return repository.artifact_file(repository.get_task(db, task_id), artifact_id)


def download_archive(db: Session, task_id: str):
    return build_archive(repository.get_task(db, task_id))


def datasets(db: Session) -> list[dict]:
    return dataset_options.list_datasets(db)


def resume(db: Session, task_id: str, request: ResumeRequest, key: str | None) -> dict:
    with db.begin():
        source = repository.get_task(db, task_id, lock=True)
        config_json = {**source.config, **request.model_dump(exclude_none=True)}
        config = TrainingConfig.model_validate(config_json)
        config_json = config.model_dump(mode="json")
        if key:
            db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"training:{key}", 0))))
            previous = db.scalar(select(TrainingTask).where(TrainingTask.idempotency_key == key))
            if previous is not None:
                if previous.config != config_json or previous.resume_from_task_id != task_id:
                    raise Conflict("该请求已提交，请重新填写任务后再提交")
                return task_response(previous, repository.get_model_version(db, previous.id))
        active_resume = db.scalar(select(TrainingTask.id).where(
            TrainingTask.resume_from_task_id == task_id, TrainingTask.status.in_(ACTIVE),
        ).limit(1))
        if active_resume:
            raise Conflict("该任务已有正在排队或运行的恢复训练")
        validate_device(config.deviceId)
        artifact, _, epoch = resume_service.validate_source(source)
        repository.reserve_task_name(db, config.name)
        task = TrainingTask(
            idempotency_key=key, dataset_id=source.dataset_id, dataset_name=source.dataset_name,
            dataset_image_count=source.dataset_image_count, dataset_class_count=source.dataset_class_count,
            dataset_revision=source.dataset_revision, config=config_json, model_name=source.model_name,
            architecture=source.architecture, status="queued", phase="queued",
            parent_model_version_id=source.parent_model_version_id, resume_from_task_id=source.id,
            resume_checkpoint={"artifactId": artifact["id"], "sha256": artifact["sha256"], "epoch": epoch + 1},
        )
        db.add(task)
        db.flush()
        return task_response(task)

