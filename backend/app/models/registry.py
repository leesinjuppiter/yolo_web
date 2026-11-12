"""Registry queries and comparison, preserving immutable training lineage."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dataset.repository import Conflict, NotFound
from app.evaluation.models import EvaluationRun
from app.evaluation.repository import response
from app.models.training_versions import ModelVersion
from app.model_exports.models import ExportTask
from app.training.models import TrainingTask


def get_pair(db: Session, version_id: str):
    row = db.execute(select(ModelVersion, TrainingTask).join(
        TrainingTask, ModelVersion.task_id == TrainingTask.id).where(ModelVersion.id == version_id)).first()
    if row is None:
        raise NotFound("模型版本不存在")
    return row


def latest_evaluation(db: Session, version_id: str):
    return db.scalar(select(EvaluationRun).where(EvaluationRun.version_id == version_id,
        EvaluationRun.status == "succeeded").order_by(EvaluationRun.created_at.desc(), EvaluationRun.id.desc()).limit(1))


def item(version: ModelVersion, task: TrainingTask, evaluation: EvaluationRun | None) -> dict:
    name = version.display_name or task.config["name"]
    actions = ["restore"] if version.lifecycle == "archived" else ["archive", "finetune"]
    if version.lifecycle != "archived" and task.config["task"] in ("detect", "obb"):
        actions.extend(["evaluate", "export"])
    return {"id": version.id, "name": name, "displayName": name, "description": version.description,
            "version": f"v{version.number}", "taskType": task.config["task"], "taskId": task.id,
            "sourceTaskId": task.id, "datasetId": task.dataset_id, "datasetName": task.dataset_name,
            "snapshotDigest": (task.snapshot or {}).get("digest"), "sha256": version.sha256,
            "createdAt": version.created_at, "lifecycle": version.lifecycle,
            "trainingMetrics": task.metrics, "validationStatus": "evaluated" if evaluation else "unverified",
            "evaluation": response(evaluation) if evaluation else None,
            "actions": actions}


def listing(db: Session, query: str = "", task: str | None = None, lifecycle: str | None = None,
            page: int = 1, page_size: int = 10) -> dict:
    statement = select(ModelVersion, TrainingTask).join(TrainingTask, ModelVersion.task_id == TrainingTask.id)
    if query:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = statement.where(func.coalesce(ModelVersion.display_name,
                                   TrainingTask.config["name"].astext).ilike(f"%{escaped}%", escape="\\"))
    if task:
        statement = statement.where(TrainingTask.config["task"].astext == task)
    if lifecycle:
        statement = statement.where(ModelVersion.lifecycle == lifecycle)
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    rows = db.execute(statement.order_by(ModelVersion.number.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    ranked = select(EvaluationRun.id, func.row_number().over(
        partition_by=EvaluationRun.version_id,
        order_by=(EvaluationRun.created_at.desc(), EvaluationRun.id.desc()),
    ).label('position')).where(EvaluationRun.status == 'succeeded',
                             EvaluationRun.version_id.in_([version.id for version, _ in rows])).subquery()
    evaluations = {row.version_id: row for row in db.scalars(select(EvaluationRun)
        .join(ranked, EvaluationRun.id == ranked.c.id).where(ranked.c.position == 1))}
    summary = {"total": db.scalar(select(func.count()).select_from(ModelVersion)),
               "archived": db.scalar(select(func.count()).select_from(ModelVersion).where(ModelVersion.lifecycle == "archived")),
               "evaluated": db.scalar(select(func.count(func.distinct(EvaluationRun.version_id))).where(
                   EvaluationRun.status == "succeeded"))}
    return {"items": [item(version, source, evaluations.get(version.id)) for version, source in rows], "total": total,
            "page": page, "pageSize": page_size, "summary": summary}


def detail(db: Session, version_id: str) -> dict:
    version, task = get_pair(db, version_id)
    result = item(version, task, latest_evaluation(db, version.id))
    result.update(config=task.config, artifacts=[
        {**{key: value for key, value in asset.items() if key != "path"},
         "url": f"/api/training/{task.id}/artifacts/{asset['id']}"} for asset in task.artifacts],
        evaluations=[response(row) for row in db.scalars(select(EvaluationRun).where(
            EvaluationRun.version_id == version_id).order_by(EvaluationRun.created_at.desc()).limit(100))])
    return result


def update(db: Session, version_id: str, metadata) -> dict:
    with db.begin():
        version, task = get_pair(db, version_id)
        version.display_name, version.description = metadata.displayName.strip(), metadata.description.strip()
        if not version.display_name:
            raise ValueError("模型名称不能为空")
        db.flush()
        return item(version, task, latest_evaluation(db, version.id))


def lifecycle(db: Session, version_id: str, archived: bool) -> dict:
    with db.begin():
        version, task = get_pair(db, version_id)
        version.lifecycle = "archived" if archived else "candidate"
        db.flush()
        return item(version, task, latest_evaluation(db, version.id))


def delete_version(db: Session, version_id: str) -> None:
    with db.begin():
        from app.active_learning.models import Iteration

        version = db.get(ModelVersion, version_id, with_for_update=True)
        if version is None:
            raise NotFound("模型版本不存在")
        if db.scalar(select(Iteration.id).where(
                (Iteration.baseline_version_id == version_id)
                | (Iteration.result["versionId"].astext == version_id)).limit(1)):
            raise Conflict("该模型已有主动学习迭代引用，无法删除；可归档保留追溯。")
        references = (
            (EvaluationRun, EvaluationRun.version_id, "评估记录"),
            (ExportTask, ExportTask.version_id, "导出或部署包记录"),
            (TrainingTask, TrainingTask.parent_model_version_id, "后续训练任务"),
        )
        for model, field, label in references:
            if db.scalar(select(model.id).where(field == version_id).limit(1)) is not None:
                raise Conflict(f"该模型已有{label}引用，无法删除；可使用归档保留追溯关系。")
        db.delete(version)


def compare(db: Session, request) -> dict:
    ids = [str(value) for value in request.versionIds]
    baseline = str(request.baselineId)
    if len(set(ids)) != len(ids) or baseline not in ids:
        raise ValueError("对比版本不能重复，且必须包含基准模型")
    models = [detail(db, version_id) for version_id in ids]
    if len({row["taskType"] for row in models}) != 1:
        raise ValueError("只能比较相同任务类型的模型")
    reports = [(row["evaluation"] or {}).get("report") for row in models]
    reasons = []
    if not all(reports):
        reasons.append("部分模型尚未完成独立评估；训练验证指标仅供来源展示")
    elif len({report.get("protocolDigest") for report in reports}) != 1:
        reasons.append("评估数据或评估协议不一致，不能进行精度排名")
    comparable = not reasons
    rows = []
    for key, label in (("map50", "mAP50"), ("map50_95", "mAP50-95"), ("precision", "Precision"), ("recall", "Recall")):
        values = {version_id: ((report or {}).get("metrics") or {}).get(key)
                  for version_id, report in zip(ids, reports)}
        base = values[baseline]
        deltas = {version_id: (value - base if comparable and value is not None and base is not None else None)
                  for version_id, value in values.items()}
        rows.append({"key": key, "label": label, "unit": "ratio", "values": values, "deltas": deltas})
    return {"models": models, "baselineId": baseline, "comparable": comparable, "reasons": reasons, "rows": rows}


TOOLS = {"model.list": listing, "model.detail": detail, "model.update_metadata": update,
         "model.lifecycle": lifecycle, "model.compare": compare, "model.delete": delete_version}
