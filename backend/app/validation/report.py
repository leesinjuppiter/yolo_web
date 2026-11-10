from collections import Counter
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field

from app.annotation.validation import validate_annotations
from app.quality.fingerprints import ImageFacts, inspect_files


class ReportItem(BaseModel):
    label: str
    value: int | str


class ReportIssue(BaseModel):
    code: str
    severity: Literal["warning", "error"]
    message: str
    image_id: str | None = None
    related_image_id: str | None = None
    image_sha256: str | None = None
    related_image_sha256: str | None = None
    review_status: Literal["pending", "confirmed"] | None = None


class DatasetReport(BaseModel):
    title: str
    items: list[ReportItem] = Field(default_factory=list)
    messages: list[str] = Field(default_factory=list)
    issues: list[ReportIssue] = Field(default_factory=list)
    class_counts: dict[str, int] = Field(default_factory=dict)


def _image_issues(dataset, image, class_ids: set[str], facts: ImageFacts) -> list[ReportIssue]:
    issues = []
    if image.split is None:
        issues.append(ReportIssue(code="split_missing", severity="warning", message=f"{image.name}：尚未分配分集", image_id=image.id))
    try:
        if facts.error:
            raise ValueError(facts.error)
        if facts.dimensions != (image.width, image.height):
            raise ValueError("原图尺寸与已保存的记录不一致")
        validate_annotations(task_type=dataset.task_type, width=image.width, height=image.height,
                             keypoint_names=dataset.keypoint_names, class_ids=class_ids, status=image.status,
                             annotations=image.annotations, serialize=False)
    except ValueError as exc:
        issues.append(ReportIssue(code="image_invalid", severity="error", message=f"{image.name}：{exc}", image_id=image.id))
    return issues


def validate_dataset(dataset, facts: Sequence[ImageFacts] | None = None) -> DatasetReport:
    class_ids = {item.id for item in dataset.classes}
    issues = []
    if not dataset.images:
        issues.append(ReportIssue(code="dataset_empty", severity="warning", message="当前数据集没有图片"))
    split_counts = Counter(image.split for image in dataset.images if image.status == "annotated")
    if dataset.images:
        for split in ("train", "val"):
            if not split_counts[split]:
                issues.append(ReportIssue(code="split_no_positive", severity="warning", message=f"{split} 分集尚无正样本"))
    unlabeled = sum(image.status == "unlabeled" for image in dataset.images)
    if unlabeled:
        issues.append(ReportIssue(code="unlabeled_images", severity="warning", message=f"{unlabeled} 张图片尚未标注，导出时跳过"))
    if facts is None:
        facts = list(inspect_files(image.storage_path for image in dataset.images))
    if len(facts) != len(dataset.images):
        raise ValueError("图片与检查记录数量不一致")
    for image, inspected in zip(dataset.images, facts):
        issues.extend(_image_issues(dataset, image, class_ids, inspected))
    issues.extend(_cross_split_issues(dataset, facts))
    errors = sum(issue.severity == "error" for issue in issues)
    warnings = len(issues) - errors
    title = "发现校验错误" if errors else "校验通过，有警告" if warnings else "校验通过"
    return DatasetReport(
        title=title,
        items=[ReportItem(label="错误", value=errors), ReportItem(label="警告", value=warnings)],
        messages=[issue.message for issue in issues],
        issues=issues,
    )


def _cross_split_issues(dataset, facts: Sequence[ImageFacts]) -> list[ReportIssue]:
    issues = []
    first_seen = {}
    for image, inspected in zip(dataset.images, facts):
        if image.split is None or inspected.exact is None:
            continue
        earlier = first_seen.setdefault(inspected.exact, image)
        if earlier.split != image.split:
            issues.append(ReportIssue(
                code="duplicate_across_splits", severity="warning", image_id=image.id, related_image_id=earlier.id,
                message=f"{image.name}（{image.split}）与 {earlier.name}（{earlier.split}）内容相同，可能造成数据泄漏",
            ))
    return issues
