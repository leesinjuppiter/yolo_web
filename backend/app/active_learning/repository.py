from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.active_learning.models import Candidate, Iteration, RecommendationTask
from app.active_learning.storage import digest
from app.dataset.models import DatasetImage
from app.dataset.repository import NotFound, serialize_classes, serialize_image
from app.training.models import TrainingTask


def class_values(dataset):
    return [item.model_dump(mode="json") for item in serialize_classes(dataset)]


def get(db: Session, model, identifier: str, lock=False):
    query = select(model).where(model.id == str(identifier))
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise NotFound("主动学习记录不存在")
    return row


def require_open(db: Session, identifier: str) -> Iteration:
    from app.dataset.repository import Conflict
    row = get(db, Iteration, identifier, True)
    if row.completed_at:
        raise Conflict("迭代已完成，请创建下一轮")
    return row


def review_valid(candidate, image, classes) -> bool:
    review = candidate.review
    return bool(review and image and not image.excluded_at and image.split not in ("val", "test")
                and review["version"] == image.version and review["classDigest"] == digest(classes))


def counts(db: Session, iteration: Iteration, dataset) -> dict:
    classes = class_values(dataset)
    items = db.scalars(select(Candidate).where(Candidate.iteration_id == iteration.id,
                                              Candidate.selected.is_(True))).all()
    result = {"selected": len(items), "reviewed": 0, "pending": 0, "new": 0, "revised": 0, "unchanged": 0}
    originals = {row.get("image_id"): row for row in iteration.source["samples"] if row["split"] == "train"}
    for item in items:
        image = db.get(DatasetImage, item.image_id)
        if not review_valid(item, image, classes):
            result["pending"] += 1
            continue
        result["reviewed"] += 1
        old = originals.get(item.image_id)
        key = "new" if old is None else ("unchanged" if old.get("annotations") == item.review["annotations"] else "revised")
        result[key] += 1
    return result


def iteration_response(db: Session, row: Iteration) -> dict:
    from app.dataset.repository import get_dataset
    from app.models.training_versions import ModelVersion
    dataset = get_dataset(db, row.dataset_id, include_images=False)
    count = counts(db, row, dataset)
    attempts = db.scalars(select(TrainingTask).where(TrainingTask.config["iterationId"].astext == row.id)
                         .order_by(TrainingTask.created_at.desc())).all()
    phase = ("completed" if row.completed_at else
             "training" if any(task.status in ("queued", "running") for task in attempts) else
             "awaiting_evaluation" if row.result or any(task.status == "succeeded" for task in attempts) else
             "ready_to_train" if count["selected"] and not count["pending"] else
             "reviewing" if count["selected"] else "preparing")
    return {"id": row.id, "name": row.name, "goal": row.goal, "datasetId": row.dataset_id,
            "datasetName": dataset.name, "taskType": row.task_type, "baselineVersionId": row.baseline_version_id,
            "sourceTaskId": row.source_task_id, "phase": phase, "status": phase, "counts": count,
            "classes": class_values(dataset), "createdAt": row.created_at, "result": row.result,
            "resultVersionId": row.result.get("versionId"),
            "baselineEvaluationId": row.result.get("baselineEvaluationId"),
            "resultEvaluationId": row.result.get("resultEvaluationId"),
            "tasks": [task_response(task) for task in db.scalars(select(RecommendationTask)
                      .where(RecommendationTask.iteration_id == row.id).order_by(RecommendationTask.created_at.desc()))],
            "completedAt": row.completed_at, "trainingAttempts": [
                {"id": task.id, "status": task.status, "name": task.config["name"], "createdAt": task.created_at,
                 "modelVersionId": db.scalar(select(ModelVersion.id).where(ModelVersion.task_id == task.id))}
                for task in attempts]}


def task_response(row: RecommendationTask) -> dict:
    return {"id": row.id, "iterationId": row.iteration_id, "config": row.config, "strategy": row.config["strategy"],
            "status": row.status, "phase": row.phase, "processed": row.processed, "total": row.total,
            "error": row.error, "createdAt": row.created_at, "finishedAt": row.finished_at,
            "cancelRequested": row.cancel_requested,
            "actions": ["cancel"] if row.status in ("queued", "running") and not row.cancel_requested else []}


def candidate_response(db: Session, row: Candidate, dataset, *, detail=True) -> dict:
    if row.purpose == "reference":
        return reference_response(db, row, detail=detail)
    image = db.get(DatasetImage, row.image_id)
    classes = class_values(dataset)
    record = serialize_image(image, {item.id: item.index for item in dataset.classes}) if image else None
    if record:
        record = record.model_dump(mode="json") if hasattr(record, "model_dump") else record
        record["src"] = record["url"]
        if not detail:
            record["annotations"] = []
    src = f"/api/datasets/{dataset.id}/images/{row.image_id}/content"
    return {"id": row.id, "iterationId": row.iteration_id, "taskId": row.task_id, "imageId": row.image_id,
            "name": row.data.get("name", image.name if image else row.image_id), "purpose": row.purpose,
            "selected": row.selected, "reviewState": "reviewed" if review_valid(row, image, classes) else "pending",
            "reasons": row.data.get("reasons", []), "confidence": row.data.get("confidence"),
            "thumbnailUrl": src.replace("/content", "/thumbnail"), "image": record, "classes": classes,
            "predictions": row.data.get("predictions", []) if detail else [], "evidence": row.data if detail else {},
            "unsupportedPrediction": row.data.get("unsupportedPrediction", False),
            "referenceIds": row.data.get("referenceIds", []), "review": row.review if detail else None}


def reference_response(db: Session, row: Candidate, *, detail=True) -> dict:
    iteration = get(db, Iteration, row.iteration_id)
    classes = [{"id": item["id"], "name": item["name"], "index": item["index"],
                "color": item.get("color", "#4f6885")} for item in iteration.source["classes"]]
    diagnostic = row.data["diagnostic"]
    src = f"/api/evaluations/{row.data['evaluationId']}/images/{row.image_id}/content"
    ground_truth = diagnostic["groundTruth"] if detail else []
    predictions = []
    if detail:
        for index, item in enumerate(diagnostic["predictions"]):
            label = classes[item["classIndex"]]
            shape = "polygon" if "polygon" in item else item["type"]
            geometry = item[shape] if shape in item else None
            if geometry is None:
                continue
            predictions.append({"id": f"reference:{index}", "class_id": label["id"],
                                "class_index": label["index"], "source": "imported", "type": shape, shape: geometry})
    image = {"id": row.image_id, "name": row.data["name"], "src": src, "url": src,
             "width": diagnostic["width"], "height": diagnostic["height"], "split": "val",
             "version": diagnostic.get("annotationVersion") or 0,
             "status": "annotated" if diagnostic["groundTruth"] else "negative", "annotations": ground_truth}
    return {"id": row.id, "iterationId": row.iteration_id, "taskId": row.task_id, "imageId": row.image_id,
            "name": row.data["name"], "purpose": "reference", "selected": False, "reviewState": "reference",
            "reasons": row.data["reasons"], "confidence": None, "image": image, "classes": classes,
            "predictions": predictions, "thumbnailUrl": src.replace("/content", "/thumbnail"),
            "referenceIds": [], "evidence": row.data if detail else {}, "review": None,
            "unsupportedPrediction": any(item.get("editable") is False for item in diagnostic["predictions"])}


def page(db: Session, query, page: int, page_size: int, serialize) -> dict:
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    rows = db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [serialize(row) for row in rows], "total": total, "page": page, "pageSize": page_size}


def log(task, message: str):
    task.logs = [*task.logs, {"sequence": len(task.logs) + 1, "time": datetime.now(timezone.utc).isoformat(),
                              "message": message}]
