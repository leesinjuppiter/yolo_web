from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Literal

from app.quality.fingerprints import ImageFacts, inspect_files
from app.quality.review_models import ReviewPair, StoredDecision, pair_key
from app.validation.report import DatasetReport, ReportIssue, ReportItem


def quality_report(dataset, image_counts: Counter[str], classes: Counter[str]) -> DatasetReport:
    annotated, negative, unlabeled = (image_counts[key] for key in ("annotated", "negative", "unlabeled"))
    image_total = sum(image_counts.values())
    coverage = f"{(annotated + negative) / image_total:.1%}" if image_total else "—"
    return DatasetReport(
        title="数据质量报告",
        items=[
            ReportItem(label="已检查覆盖率", value=coverage),
            ReportItem(label="已标注", value=annotated),
            ReportItem(label="负样本", value=negative),
            ReportItem(label="未标注", value=unlabeled),
            ReportItem(label="标注总数", value=sum(classes.values())),
        ],
        messages=[f"{item.name}：{classes[item.id]} 个标注" for item in sorted(dataset.classes, key=lambda row: row.index)],
        class_counts={item.id: classes[item.id] for item in dataset.classes},
    )


def duplicate_report(
    images: Sequence[tuple[str, str]], facts: Sequence[ImageFacts] | None = None, *,
    image_ids: Sequence[str] | None = None,
    reviews: Mapping[ReviewPair, StoredDecision] | None = None,
) -> DatasetReport:
    if facts is not None and len(facts) != len(images) or image_ids is not None and len(image_ids) != len(images):
        raise ValueError("图片与检查记录数量不一致")
    if reviews is not None and image_ids is None:
        raise ValueError("重复图审核需要图片 ID")
    checked = facts if facts is not None else inspect_files(path for _, path in images)
    files: dict[str, int] = {}
    fingerprints: dict[int, str] = {}
    duplicates = pending = invalid = 0
    messages = []
    issues = []

    def record(code: str, message: str, index: int, related: int | None = None,
               status: Literal["pending", "confirmed"] | None = None) -> None:
        messages.append(message)
        if image_ids is not None:
            issues.append(ReportIssue(
                code=code, severity="error" if related is None else "warning", message=message, image_id=image_ids[index],
                related_image_id=image_ids[related] if related is not None else None,
                image_sha256=fingerprints[index] if status else None,
                related_image_sha256=fingerprints[related] if status and related is not None else None, review_status=status,
            ))

    for index, ((name, _), inspected) in enumerate(zip(images, checked)):
        exact = inspected.exact
        if exact is None or inspected.error is not None:
            invalid += 1
            record("image_invalid", f"{name}：无法读取图片", index)
            continue
        fingerprints[index] = exact
        related = files.setdefault(exact, index)
        if related == index:
            continue
        duplicates += 1
        if reviews and image_ids is not None:
            key = pair_key(image_ids[index], image_ids[related], exact, exact)
            if reviews.get(key) == "keep_both":
                continue
        pending += 1
        record("duplicate_exact", f"{name} 与 {images[related][0]} 的文件内容相同", index, related,
               "pending" if reviews is not None else None)

    confirmed = 0
    if reviews and image_ids is not None:
        positions = {image_id: index for index, image_id in enumerate(image_ids)}
        for (first, second, first_sha, second_sha), decision in sorted(reviews.items()):
            index, related = positions.get(first), positions.get(second)
            if decision != "keep_both" or first_sha != second_sha or index is None or related is None:
                continue
            if fingerprints.get(index) == first_sha and fingerprints.get(related) == second_sha:
                confirmed += 1
                record("duplicate_exact", f"{images[index][0]} 与 {images[related][0]} 已确认重复并保留", index, related,
                       "confirmed")
    return DatasetReport(
        title="精确重复分析",
        items=[
            ReportItem(label="精确重复", value=duplicates),
            ReportItem(label="待审核", value=pending),
            ReportItem(label="无效图片", value=invalid),
            ReportItem(label="分析图片", value=len(images) - invalid),
        ] + ([ReportItem(label="已确认重复", value=confirmed)] if reviews is not None else []),
        messages=["按文件 SHA-256 查找精确重复，可并排核验后决定保留哪些样本。", *messages],
        issues=issues,
    )
