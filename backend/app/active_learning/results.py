from datetime import datetime, timezone

from app.active_learning import repository as repo
from app.active_learning.models import Iteration
from app.dataset.repository import Conflict
from app.evaluation.models import EvaluationRun
from app.models.training_versions import ModelVersion
from app.training.models import TrainingTask


def _reports(db, iteration):
    result = iteration.result
    if not result:
        return {"comparable": False, "reasons": ["尚未指定本轮结果模型及评估报告"], "rows": []}
    base = repo.get(db, EvaluationRun, result["baselineEvaluationId"])
    candidate = repo.get(db, EvaluationRun, result["resultEvaluationId"])
    reasons = []
    if base.status != "succeeded" or candidate.status != "succeeded":
        reasons.append("评估尚未完成")
    elif not base.report.get("protocolDigest") or base.report["protocolDigest"] != candidate.report.get("protocolDigest"):
        reasons.append("评估集合或协议不一致")
    rows = []
    for name in ("map50", "map50_95", "precision", "recall", "maskMap50", "maskMap50_95", "maskPrecision", "maskRecall"):
        if iteration.task_type != "segment" and name.startswith("mask"):
            continue
        a, b = (base.report or {}).get("metrics", {}).get(name), (candidate.report or {}).get("metrics", {}).get(name)
        rows.append({"key": name, "label": name, "baseline": a, "result": b,
                     "delta": b - a if not reasons and a is not None and b is not None else None})
    return {"comparable": not reasons, "reasons": reasons, "rows": rows, **result}


def choose(db, identifier, request):
    with db.begin():
        iteration = repo.require_open(db, identifier)
        version = repo.get(db, ModelVersion, str(request.versionId))
        task = repo.get(db, TrainingTask, version.task_id)
        if task.status != "succeeded" or task.config.get("iterationId") != iteration.id:
            raise ValueError("结果模型必须来自本轮成功训练并已注册")
        for run_id, version_id, source_id in ((request.baselineEvaluationId, iteration.baseline_version_id,
                                               iteration.source_task_id),
                                              (request.resultEvaluationId, version.id, task.id)):
            run = repo.get(db, EvaluationRun, str(run_id))
            if (run.version_id != version_id or run.config.get("purpose") != "diagnostic"
                    or (run.config.get("sourceTaskId") or source_id) != iteration.source_task_id):
                raise ValueError("需要对应模型在本轮固定 val 上的诊断报告")
        iteration.result = request.model_dump(mode="json")
        return _reports(db, iteration)


def comparison(db, identifier):
    return _reports(db, repo.get(db, Iteration, identifier))


def complete(db, identifier):
    with db.begin():
        iteration = repo.require_open(db, identifier)
        result = _reports(db, iteration)
        if not result["comparable"]:
            raise Conflict("请先完成同口径 val 评估并指定本轮结果")
        iteration.completed_at = datetime.now(timezone.utc)
        return repo.iteration_response(db, iteration)
