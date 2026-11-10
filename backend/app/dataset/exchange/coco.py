"""Read COCO instances from ZIP or a local directory and persist them in the workbench."""

import json
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Collection
from functools import partial
from itertools import groupby
from math import inf
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Literal
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.annotation.schemas import MAX_POLYGON_VERTICES
from app.annotation.validation import validate_annotations
from app.core.storage import remove_images, resolve_image, save_image
from app.dataset import repository, schemas
from app.dataset.analysis.queue import REPORT_KINDS, invalidate_reports

from .archive import IMAGE_EXTENSIONS, MAX_ARCHIVE_BYTES, MAX_IMAGE_BYTES, archive_reference, inspect_members, read_bytes
from .local_directory import directory_members, directory_root, read_directory_file
from .service import CLASS_COLORS

CocoTask = Literal["detect", "segment"]
Point = tuple[float, float]
MAX_COCO_JSON_BYTES = 512 * 1024 * 1024
_SPLIT = re.compile(r"(?:^|[._-])(train|val|valid|test)(?:[0-9]{4})?(?=$|[._-])", re.IGNORECASE)


class CocoSkippedSample(BaseModel):
    manifest: str
    filename: str
    reason: str


class CocoImportResponse(schemas.DatasetResponse):
    skipped_samples: list[CocoSkippedSample]


def _split(parts: Collection[str], *, manifest_name: bool = False) -> str | None:
    for part in parts:
        match = _SPLIT.search(part) if manifest_name else _SPLIT.fullmatch(part)
        if match:
            split = match.group(1).lower()
            return "val" if split == "valid" else split
    return None


def _manifest_paths(files: Collection[PurePosixPath]) -> list[PurePosixPath]:
    candidates = sorted(
        path for path in files if path.suffix.lower() == ".json"
        and not path.name.lower().startswith(("captions_", "person_keypoints_", "panoptic_", "stuff_"))
    )
    recognized = [path for path in candidates if path.name.lower().startswith(("instances_", "image_info_"))
                  or path.name.lower() in {"_annotations.coco.json", "annotations.json", "instances.json"}]
    return recognized or candidates


def _rows(doc: dict, key: str, *, optional: bool = False) -> list[dict]:
    rows = doc.get(key, [] if optional else None)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"COCO 的 {key} 须为对象数组")
    return rows


def _read_manifest(path: PurePosixPath, bytes_at: Callable[[PurePosixPath, int], bytes]) -> dict | None:
    try:
        doc = json.loads(bytes_at(path, MAX_COCO_JSON_BYTES))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"无法读取 COCO JSON：{path}") from exc
    return doc if isinstance(doc, dict) and "images" in doc else None


def _find_image(filename: str, manifest: PurePosixPath, images: set[PurePosixPath],
                by_name: dict[str, list[PurePosixPath]], split: str | None) -> PurePosixPath:
    relative = archive_reference(PurePosixPath(), filename.replace("\\", "/"))
    candidates = [path for path in by_name.get(relative.name, []) if path.parts[-len(relative.parts):] == relative.parts]
    matching_split = [path for path in candidates if _split(path.parts[:-1]) == split] if split else []
    if matching_split:
        candidates = matching_split
    for base in manifest.parents:
        for candidate in (base / relative, base / "images" / relative):
            if candidate in images and candidate in candidates:
                return candidate
    if len(candidates) == 1:
        return candidates[0]
    reason = "存在多个同名图片，请在 file_name 中写明相对路径" if candidates else "找不到图片"
    raise ValueError(f"{reason}：{filename}")


def _annotations_for_images(doc: dict, image_ids: set[int]) -> dict[int, list[dict]]:
    result = defaultdict(list)
    for ann in _rows(doc, "annotations", optional=True):
        image_id = ann.get("image_id")
        if type(image_id) is not int or image_id not in image_ids:
            raise ValueError("COCO 标注引用了不存在的 image_id")
        result[image_id].append(ann)
    return result


def _category_map(db: Session, dataset_id: str, doc: dict, classes: dict[str, str]) -> dict[int, str]:
    rows = _rows(doc, "categories", optional=True)
    result = {}
    for category in rows:
        category_id, name = category.get("id"), category.get("name")
        if type(category_id) is not int or category_id in result or not isinstance(name, str) or not name.strip():
            raise ValueError("COCO 类别须有唯一整数 ID 和名称")
        name = name.strip()
        key = name.casefold()
        if key not in classes:
            index = len(classes)
            class_id = str(uuid4())
            repository.add_class(db, dataset_id, class_id, name, CLASS_COLORS[index % len(CLASS_COLORS)], index)
            classes[key] = class_id
        result[category_id] = classes[key]
    if len(set(result.values())) != len(result):
        raise ValueError("同一 COCO JSON 中的类别名称不能重复")
    return result


def _read_contour(coords: object) -> list[Point]:
    if (not isinstance(coords, list) or len(coords) < 4 or len(coords) % 2
            or any(type(value) not in (int, float) or not -inf < value < inf for value in coords)):
        raise ValueError("COCO 多边形须由有效坐标对组成")
    return list(zip(coords[::2], coords[1::2]))


def _filled_contours(contours: list[list[Point]]) -> list[list[Point]]:
    filled = []
    for points in contours:
        following = points[1:] + points[:1]
        area = sum(x * ny - nx * y for (x, y), (nx, ny) in zip(points, following))
        if abs(area) >= 1e-6:
            filled.append(points if area > 0 else points[::-1])
        elif Counter(zip(points, following)) != Counter(zip(following, points)):
            raise ValueError("COCO 多边形轮廓的面积必须大于零")
    if not filled:
        raise ValueError("COCO 实例至少需要一个面积大于零的多边形轮廓")
    return filled


def _without_redundant_vertices(points: list[Point]) -> list[Point]:
    points = [point for point, _ in groupby(points)]
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    result = []
    for (ax, ay), (bx, by), (cx, cy) in zip(points[-1:] + points[:-1], points, points[1:] + points[:1]):
        dx, dy, ex, ey = bx - ax, by - ay, cx - bx, cy - by
        if dx * ey != dy * ex or dx * ex + dy * ey <= 0:
            result.append((bx, by))
    return result


def _join_contours(contours: list[list[Point]]) -> list[Point]:
    polygon = contours[0]
    for contour in contours[1:]:
        _, anchor, start = min(
            ((x - px) ** 2 + (y - py) ** 2, i, j)
            for i, (x, y) in enumerate(polygon) for j, (px, py) in enumerate(contour)
        )
        # Traverse the bridge in both directions so it encloses no area.
        polygon = (polygon[:anchor + 1] + contour[start:] + contour[:start + 1] + polygon[anchor:])
    return polygon


def _segmentation_polygon(annotation: dict) -> list[Point]:
    segmentation = annotation.get("segmentation")
    if annotation.get("iscrowd") or isinstance(segmentation, dict):
        raise ValueError("实例分割导入需要多边形，当前不能导入 RLE 或 crowd 掩码")
    if not isinstance(segmentation, list) or not segmentation:
        raise ValueError("实例分割导入要求每个对象至少包含一个多边形轮廓")
    contours = [_read_contour(coords) for coords in segmentation]
    if len(contours) > 1:
        contours = _filled_contours(contours)
    elif len(contours[0]) < 3:
        raise ValueError("COCO 多边形须包含至少三个坐标对")
    bridge_vertices = 2 * (len(contours) - 1)
    count = sum(map(len, contours)) + bridge_vertices
    if count > MAX_POLYGON_VERTICES:
        reduced = [_without_redundant_vertices(points) for points in contours]
        reduced_count = sum(map(len, reduced)) + bridge_vertices
        if min(map(len, reduced)) < 3 or reduced_count > MAX_POLYGON_VERTICES:
            raise ValueError(f"COCO 多边形有 {count} 个顶点，超过 {MAX_POLYGON_VERTICES} 个顶点的上限")
        contours = reduced
    return _join_contours(contours)


def _geometry(annotation: dict, task: CocoTask) -> dict:
    if task == "detect":
        bbox = annotation.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4 or any(type(value) not in (int, float) for value in bbox):
            raise ValueError("COCO 检测标注须包含 bbox [x, y, width, height]")
        return {"type": "bbox", "bbox": dict(zip(("x", "y", "width", "height"), bbox))}
    return {"type": "polygon", "polygon": _segmentation_polygon(annotation)}


def _import_manifest(db: Session, dataset_id: str, task: CocoTask, doc: dict, manifest: PurePosixPath,
                     locate, bytes_at, classes: dict[str, str], saved_paths: list[str], seen: set[PurePosixPath],
                     skipped: list[CocoSkippedSample] | None) -> None:
    class_map = _category_map(db, dataset_id, doc, classes)
    image_rows = _rows(doc, "images")
    ids = [row.get("id") for row in image_rows]
    if any(type(value) is not int for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("COCO 图片须有唯一整数 ID")
    grouped = _annotations_for_images(doc, set(ids))
    class_ids = set(class_map.values())
    split_hint = _split((manifest.stem,), manifest_name=True) or _split(tuple(reversed(manifest.parent.parts)))
    for row in image_rows:
        filename = row.get("file_name")
        sample_name = filename if isinstance(filename, str) and filename.strip() else f"image_id={row['id']}"
        stored = None
        try:
            if not isinstance(filename, str) or not filename.strip():
                raise ValueError("COCO 图片缺少 file_name")
            path = locate(filename, manifest, split_hint)
            split = _split(tuple(reversed(path.parent.parts)))
            if split and split_hint and split != split_hint:
                raise ValueError("图片目录与标注文件的分集不一致")
            annotations = []
            for ann in grouped.get(row["id"], []):
                category_id = ann.get("category_id")
                if type(category_id) is not int or category_id not in class_map:
                    raise ValueError("COCO 标注引用了不存在的 category_id")
                annotations.append({"id": str(uuid4()), "class_id": class_map[category_id],
                                    "source": "imported", **_geometry(ann, task)})
            stored = save_image(bytes_at(path, MAX_IMAGE_BYTES))
            saved_paths.append(stored.path)
            if ((row.get("width", stored.width), row.get("height", stored.height))
                    != (stored.width, stored.height)):
                raise ValueError("图片尺寸与 COCO JSON 中记录的尺寸不一致")
            status = "annotated" if annotations else "negative" if "annotations" in doc else "unlabeled"
            validated = validate_annotations(task_type=task, width=stored.width, height=stored.height, keypoint_names=[],
                                             class_ids=class_ids, status=status, annotations=annotations)
        except ValueError as exc:
            if skipped is None:
                raise ValueError(f"{sample_name}：{exc}") from exc
            if stored is not None:
                resolve_image(stored.path).unlink(missing_ok=True)
                saved_paths.pop()
            skipped.append(CocoSkippedSample(manifest=str(manifest), filename=sample_name, reason=str(exc)))
            continue
        except OSError as exc:
            raise ValueError(f"{sample_name}：{exc}") from exc
        if path in seen:
            raise ValueError(f"{filename}：同一图片出现在多个 COCO 记录中")
        seen.add(path)
        repository.add_image(db, dataset_id, path.name, stored.width, stored.height, split_hint or split,
                             stored.path, status=status, annotations=validated)
        if len(saved_paths) % 500 == 0:
            db.flush()


def _import_coco(db: Session, name: str, task: CocoTask, files: Collection[PurePosixPath],
                 bytes_at: Callable[[PurePosixPath, int], bytes], *, skip_invalid: bool) -> CocoImportResponse:
    images = {path for path in files if path.suffix.lower() in IMAGE_EXTENSIONS}
    by_name = defaultdict(list)
    for path in images:
        by_name[path.name].append(path)
    classes: dict[str, str] = {}
    saved_paths: list[str] = []
    seen: set[PurePosixPath] = set()
    skipped: list[CocoSkippedSample] | None = [] if skip_invalid else None

    def locate(filename: str, manifest: PurePosixPath, split: str | None) -> PurePosixPath:
        return _find_image(filename, manifest, images, by_name, split)

    try:
        dataset = repository.create_dataset(db, name, task)
        for manifest in _manifest_paths(files):
            doc = _read_manifest(manifest, bytes_at)
            if doc is None:
                continue
            try:
                _import_manifest(db, dataset.id, task, doc, manifest, locate, bytes_at, classes, saved_paths, seen, skipped)
            except ValueError as exc:
                raise ValueError(f"{manifest}：{exc}") from exc
            del doc
        if not seen:
            if skipped:
                first = skipped[0]
                raise ValueError(f"已排除全部 {len(skipped)} 个样本，未创建数据集。"
                                 f"首个问题：{first.manifest}：{first.filename}：{first.reason}")
            raise ValueError("没有找到包含可导入图片的 COCO JSON")
        response = CocoImportResponse(**dict(repository.serialize(dataset)), skipped_samples=skipped or [])
        invalidate_reports(db, dataset.id, REPORT_KINDS)
        db.commit()
        return response
    except Exception:
        db.rollback()
        remove_images(saved_paths)
        raise


def import_coco_archive(db: Session, source: BinaryIO, filename: str, task: CocoTask, *,
                        skip_invalid: bool = False) -> CocoImportResponse:
    if source.seek(0, 2) > MAX_ARCHIVE_BYTES:
        raise ValueError("ZIP 文件不能超过 256 MiB")
    source.seek(0)
    name = Path(filename.replace("\\", "/")).stem[:120] or "COCO 数据集"
    try:
        with ZipFile(source) as archive:
            files = inspect_members(archive)

            def bytes_at(path: PurePosixPath, limit: int) -> bytes:
                return read_bytes(archive, files[path], limit)

            return _import_coco(db, name, task, files, bytes_at, skip_invalid=skip_invalid)
    except (BadZipFile, NotImplementedError, EOFError) as exc:
        raise ValueError("无法读取 ZIP 或不支持此压缩方式") from exc


def import_coco_directory(db: Session, folder: str, task: CocoTask, *,
                          skip_invalid: bool = False) -> CocoImportResponse:
    root = directory_root(folder)
    files = directory_members(root, extra_suffixes=frozenset({".json"}))
    return _import_coco(db, root.name[:120], task, files, partial(read_directory_file, root), skip_invalid=skip_invalid)
