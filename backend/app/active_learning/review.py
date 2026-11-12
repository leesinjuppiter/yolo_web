from sqlalchemy import select

from app.active_learning import repository as repo, storage
from app.active_learning.models import Candidate, Iteration
from app.annotation.validation import validate_annotations
from app.dataset import repository as datasets
from app.dataset.models import DatasetImage
from app.dataset.analysis.queue import invalidate_reports


def assert_trainable(iteration, image, sha):
    protected = {row["image_sha256"] for row in iteration.source["samples"] if row["split"] in ("val", "test")}
    if image.dataset_id != iteration.dataset_id or image.split in ("val", "test") or sha in protected or image.excluded_at:
        raise datasets.Conflict("验证/测试图片或排除图片不能进入本轮训练")


def upsert_candidate(db, iteration, image_id, purpose, data, task_id=None):
    row = db.scalar(select(Candidate).where(Candidate.iteration_id == iteration.id,
        Candidate.image_id == image_id, Candidate.purpose == purpose))
    if row is None:
        row = Candidate(iteration_id=iteration.id, image_id=image_id, purpose=purpose, data=data, task_id=task_id)
        db.add(row)
    else:
        merged = {**row.data, **data}
        merged["reasons"] = list(dict.fromkeys(row.data.get("reasons", []) + data.get("reasons", [])))
        merged["taskIds"] = list(dict.fromkeys(row.data.get("taskIds", []) + data.get("taskIds", [])))
        merged["referenceIds"] = row.data.get("referenceIds", [])
        row.data = merged
    db.flush()
    return row


def add_candidates(db, iteration_id, request):
    with db.begin():
        iteration = repo.require_open(db, iteration_id)
        identifiers = []
        for identifier in dict.fromkeys(map(str, request.imageIds)):
            image = datasets.get_image(db, iteration.dataset_id, identifier)
            sha = storage.image_digest(image)
            assert_trainable(iteration, image, sha)
            row = upsert_candidate(db, iteration, image.id, "training", {"name": image.name,
                "imageSha256": sha, "version": image.version, "reasons": [request.reason]})
            identifiers.append(row.id)
        return {"added": len(identifiers), "candidateIds": identifiers}


def select_candidates(db, iteration_id, request):
    with db.begin():
        iteration = repo.require_open(db, iteration_id)
        for identifier in set(map(str, request.candidateIds)):
            row = repo.get(db, Candidate, identifier, True)
            if row.iteration_id != iteration.id or row.purpose != "training":
                raise ValueError("问题参考不能加入训练复核队列")
            if request.selected:
                image = datasets.get_image(db, iteration.dataset_id, row.image_id)
                assert_trainable(iteration, image, storage.image_digest(image))
            row.selected = request.selected
        return {"updated": len(set(request.candidateIds))}


def link_reference(db, candidate_id, request):
    with db.begin():
        row = repo.get(db, Candidate, candidate_id, True)
        repo.require_open(db, row.iteration_id)
        if row.purpose != "training":
            raise ValueError("只能为训练候选关联问题参考")
        for identifier in request.referenceIds:
            reference = repo.get(db, Candidate, str(identifier))
            if reference.iteration_id != row.iteration_id or reference.purpose != "reference":
                raise ValueError("问题参考必须属于同一迭代")
        row.data = {**row.data, "referenceIds": list(map(str, request.referenceIds))}
        return {"referenceIds": row.data["referenceIds"]}


def confirm(db, candidate_id, request):
    with db.begin():
        row = repo.get(db, Candidate, candidate_id, True)
        iteration = repo.require_open(db, row.iteration_id)
        dataset = datasets.get_dataset(db, iteration.dataset_id, lock=True, include_images=False)
        image = datasets.get_image(db, iteration.dataset_id, row.image_id)
        if row.purpose != "training" or not row.selected:
            raise ValueError("请先将训练候选加入复核队列")
        sha = storage.image_digest(image)
        assert_trainable(iteration, image, sha)
        if image.version != request.version:
            raise datasets.Conflict("标注版本发生变化，请重新加载并确认")
        if request.status == "negative" and not request.negativeConfirmed:
            raise ValueError("负样本需要明确确认无目标")
        values = validate_annotations(task_type=dataset.task_type, width=image.width, height=image.height,
            keypoint_names=[], class_ids={entry.id for entry in dataset.classes},
            status=request.status, annotations=request.annotations)
        image.annotations, image.status = values, request.status
        image.version += 1
        row.review = {"version": image.version, "imageSha256": sha,
            "classDigest": storage.digest(repo.class_values(dataset)), "annotations": values,
            "status": image.status, "negativeConfirmed": request.negativeConfirmed}
        invalidate_reports(db, dataset.id, ("validate", "quality"))
        return repo.candidate_response(db, row, dataset)
