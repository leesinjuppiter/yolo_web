from collections import Counter

from PIL import Image, ImageOps

from app.core.storage import resolve_image
from app.quality.fingerprints import exact_fingerprint
from app.validation.report import DatasetReport, ReportItem


def quality_report(dataset) -> DatasetReport:
    image_counts = Counter(image.status for image in dataset.images)
    classes = Counter(annotation["class_id"] for image in dataset.images for annotation in image.annotations)
    annotated, negative, unlabeled = (image_counts[key] for key in ("annotated", "negative", "unlabeled"))
    coverage = f"{(annotated + negative) / len(dataset.images):.1%}" if dataset.images else "—"
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
    )


def _fingerprints(path) -> tuple[str, int]:
    exact = exact_fingerprint(path)
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("L").resize((9, 8), Image.Resampling.LANCZOS)
        pixels = list(image.getdata())
    differences = (pixels[y * 9 + x] > pixels[y * 9 + x + 1] for y in range(8) for x in range(8))
    perceptual = sum(int(value) << index for index, value in enumerate(differences))
    return exact, perceptual


def duplicate_report(dataset) -> DatasetReport:
    files: dict[str, str] = {}
    visuals: dict[int, str] = {}
    duplicates = similar = invalid = 0
    messages = []
    for image in dataset.images:
        try:
            exact, visual = _fingerprints(resolve_image(image.storage_path))
        except (ValueError, OSError, Image.DecompressionBombError):
            invalid += 1
            messages.append(f"{image.name}：无法读取图片")
            continue
        if exact in files:
            duplicates += 1
            messages.append(f"{image.name} 与 {files[exact]} 的文件内容相同")
            continue
        files[exact] = image.name
        match = next((name for key, name in visuals.items() if (key ^ visual).bit_count() <= 5), None)
        if match is not None:
            similar += 1
            messages.append(f"{image.name} 与 {match} 的图像特征相近")
        visuals.setdefault(visual, image.name)
    return DatasetReport(
        title="重复／相似图分析",
        items=[
            ReportItem(label="精确重复", value=duplicates),
            ReportItem(label="相似图片", value=similar),
            ReportItem(label="无效图片", value=invalid),
            ReportItem(label="分析图片", value=len(dataset.images) - invalid),
        ],
        messages=["相似图片按灰度差异哈希筛查，可在处理前查看原图。", *messages],
    )
