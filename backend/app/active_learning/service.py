from datetime import datetime, timezone

from sqlalchemy import String, cast, func, select

from app.active_learning import repository as repo, schemas, storage
from app.active_learning.models import Candidate, Iteration, RecommendationTask
from app.dataset import repository as datasets
from app.dataset.models import Dataset, DatasetImage
from app.evaluation.models import EvaluationRun
from app.models.sources import registered_asset
from app.models.training_versions import ModelVersion
from app.training.devices import available_devices, validate_device


def options(db) -> dict:
    versions = db.scalars(select(ModelVersion).where(ModelVersion.lifecycle != "archived")).all()
    from app.training.models import TrainingTask
    models = []
    for version in versions:
        task = db.get(TrainingTask, version.task_id)
        if task.config["task"] in ("detect", "segment", "obb"):
            models.append({"id": version.id, "name": version.display_name or f"v{version.number}",
                           "taskType": task.config["task"], "datasetId": task.dataset_id,
                           "sourceTaskId": task.id})
    return {"models": models, "datasets": [{"id": row.id, "name": row.name, "taskType": row.task_type}
                                          for row in db.scalars(select(Dataset))],
            "devices": available_devices(), "evaluations": [
                {"id": row.id, "versionId": row.version_id, "config": row.config, "createdAt": row.created_at}
                for row in db.scalars(select(EvaluationRun).where(EvaluationRun.status == "succeeded"))
                if row.config.get("purpose") == "diagnostic"]}


def create_iteration(db, request: schemas.IterationRequest):
    with db.begin():
        version, task, _, _ = registered_asset(db, "version:" + str(request.baselineVersionId))
        if version.lifecycle == "archived" or task.config["task"] not in ("detect", "segment", "obb"):
            raise ValueError("基线模型不支持主动学习")
        dataset = datasets.get_dataset(db, str(request.datasetId), lock=True, include_images=False)
        if task.dataset_id != dataset.id or dataset.task_type != task.config["task"]:
            raise ValueError("首版必须使用基线来源数据集及相同任务类型")
        source = storage.load_source(task)
        source["modelSha256"] = version.sha256
        current = [(label.id, label.name) for label in dataset.classes]
        if current != [(label["id"], label["name"]) for label in source["classes"]]:
            raise ValueError("当前数据集类别与基线快照不一致")
        row = Iteration(name=request.name.strip(), goal=request.goal, dataset_id=dataset.id,
                        baseline_version_id=version.id, source_task_id=task.id,
                        task_type=dataset.task_type, source=source)
        db.add(row)
        db.flush()
        return repo.iteration_response(db, row)


def iteration_detail(db, identifier):
    return repo.iteration_response(db, repo.get(db, Iteration, identifier))


def list_iterations(db, page=1, page_size=20, query="", status=None):
    selection = select(Iteration).order_by(Iteration.created_at.desc(), Iteration.id)
    if query:
        selection = selection.where(Iteration.name.ilike("%" + query + "%") | Iteration.goal.ilike("%" + query + "%"))
    if status == "completed":
        selection = selection.where(Iteration.completed_at.is_not(None))
    elif status:
        selection = selection.where(Iteration.completed_at.is_(None))
    return repo.page(db, selection, page, page_size, lambda row: repo.iteration_response(db, row))


def overview(db):
    rows = db.scalars(select(Iteration).where(Iteration.completed_at.is_(None))).all()
    summaries = [repo.iteration_response(db, row) for row in rows]
    return {"activeIterations": len(rows), "pending": sum(row["counts"]["pending"] for row in summaries),
            "reviewed": sum(row["counts"]["reviewed"] for row in summaries),
            "awaitingEvaluation": sum(row["phase"] == "awaiting_evaluation" for row in summaries)}


def _validate_evaluation(db, iteration, evaluation_id):
    row = repo.get(db, EvaluationRun, evaluation_id)
    if (row.version_id != iteration.baseline_version_id or row.status != "succeeded"
            or row.config.get("purpose") != "diagnostic"
            or (row.config.get("sourceTaskId") or iteration.source_task_id) != iteration.source_task_id
            or not row.report or "perImage" not in row.report):
        raise ValueError("需要基线模型在本轮固定 val 上完成的逐图诊断")


def create_task(db, request: schemas.RecommendationRequest, key=None):
    config = request.model_dump(mode="json")
    with db.begin():
        if key:
            db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended("active-learning:" + key, 0))))
            old = db.scalar(select(RecommendationTask).where(RecommendationTask.idempotency_key == key))
            if old:
                if {name: value for name, value in old.config.items() if name != "modelSha256"} != config:
                    raise datasets.Conflict("幂等键已用于其他推荐配置")
                return repo.task_response(old)
        iteration = repo.require_open(db, str(request.iterationId))
        config["modelSha256"] = iteration.source["modelSha256"]
        validate_device(request.deviceId)
        if request.evaluationId:
            _validate_evaluation(db, iteration, str(request.evaluationId))
        protected = {row["image_sha256"] for row in iteration.source["samples"] if row["split"] != "train"}
        inputs = []
        if request.strategy != "error_first":
            query = select(DatasetImage).where(DatasetImage.dataset_id == iteration.dataset_id,
                DatasetImage.excluded_at.is_(None), DatasetImage.status == "unlabeled",
                (DatasetImage.split == "train") | DatasetImage.split.is_(None)).order_by(DatasetImage.id)
            for image in db.scalars(query):
                sha = storage.image_digest(image)
                if sha not in protected:
                    inputs.append({"imageId": image.id, "imageSha256": sha, "version": image.version,
                                   "storagePath": image.storage_path, "name": image.name,
                                   "width": image.width, "height": image.height})
        row = RecommendationTask(iteration_id=iteration.id, config=config, inputs=inputs,
                                 total=len(inputs), idempotency_key=key)
        db.add(row)
        db.flush()
        repo.log(row, "输入范围已冻结；等待执行器")
        return repo.task_response(row)


def cancel_task(db, identifier):
    with db.begin():
        row = repo.get(db, RecommendationTask, identifier, True)
        if row.status not in ("queued", "running"):
            raise datasets.Conflict("推荐任务已结束")
        row.cancel_requested = True
        if row.status == "queued":
            row.status = row.phase = "canceled"
            row.finished_at = datetime.now(timezone.utc)
        return repo.task_response(row)


def list_candidates(db, identifier, page=1, page_size=30, purpose=None, selected=None, reason=None, review_state=None,
                    queue=False):
    task = None if queue else repo.get(db, RecommendationTask, identifier)
    iteration = repo.get(db, Iteration, identifier if queue else task.iteration_id)
    dataset = datasets.get_dataset(db, iteration.dataset_id, include_images=False)
    query = select(Candidate).where(Candidate.iteration_id == iteration.id).order_by(Candidate.created_at, Candidate.id)
    if not queue:
        query = query.where(Candidate.data["taskIds"].contains([task.id]) | (Candidate.task_id == task.id))
    if queue:
        query = query.where(Candidate.selected.is_(True))
    if purpose:
        query = query.where(Candidate.purpose == purpose)
    if selected is not None:
        query = query.where(Candidate.selected == selected)
    if reason:
        query = query.where(Candidate.data["reasons"].contains([reason]))
    if review_state:
        current = select(DatasetImage.version).where(DatasetImage.id == Candidate.image_id).scalar_subquery()
        valid = Candidate.review["version"].as_integer() == current
        query = query.where(valid if review_state == "reviewed" else (~valid | Candidate.review.is_(None)))
    result = repo.page(db, query, page, page_size, lambda row: repo.candidate_response(db, row, dataset, detail=False))
    return {**result, "classes": datasets.serialize_classes(dataset)}


def candidate_detail(db, identifier):
    row = repo.get(db, Candidate, identifier)
    iteration = repo.get(db, Iteration, row.iteration_id)
    dataset = datasets.get_dataset(db, iteration.dataset_id, include_images=False)
    return repo.candidate_response(db, row, dataset)


def list_tasks(db, page=1, page_size=20, status=None, iteration_id=None, query=""):
    selection = select(RecommendationTask).order_by(RecommendationTask.created_at.desc(), RecommendationTask.id)
    if status:
        selection = selection.where(RecommendationTask.status == status)
    if iteration_id:
        selection = selection.where(RecommendationTask.iteration_id == str(iteration_id))
    if query:
        related = select(Iteration.id).where(Iteration.name.ilike("%" + query + "%"))
        selection = selection.where(cast(RecommendationTask.id, String).ilike("%" + query + "%")
                                    | RecommendationTask.iteration_id.in_(related))
    return repo.page(db, selection, page, page_size, repo.task_response)


def task_status(db, identifier):
    return repo.task_response(repo.get(db, RecommendationTask, identifier))


def task_logs(db, identifier, after_sequence=0):
    items = [item for item in repo.get(db, RecommendationTask, identifier).logs if item["sequence"] > after_sequence]
    return {"items": items, "nextSequence": items[-1]["sequence"] if items else after_sequence}
