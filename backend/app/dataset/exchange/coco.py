"""Read COCO instances from ZIP or a local directory and persist them in the workbench."""

import json
import re
from collections import defaultdict
from collections.abc import Callable, Collection
from functools import partial
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Literal
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from sqlalchemy.orm import Session

from app.annotation.validation import validate_annotations
from app.core.storage import remove_images, save_image
from app.dataset import repository, schemas

from .archive import IMAGE_EXTENSIONS, MAX_ARCHIVE_BYTES, MAX_IMAGE_BYTES, archive_reference, inspect_members, read_bytes
from .local_directory import directory_members, directory_root, read_directory_file
from .service import CLASS_COLORS

CocoTask = Literal["detect", "segment"]
MAX_COCO_JSON_BYTES = 512 * 1024 * 1024
_SPLIT = re.compile(r"(?:^|[._-])(train|val|valid|test)(?:[0-9]{4})?(?=$|[._-])", re.IGNORECASE)


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


def _annotations_for_images(doc: dict, image_ids: set[int], class_map: dict[int, str]) -> dict[int, list[dict]]:
    result = defaultdict(list)
    for ann in _rows(doc, "annotations", optional=True):
        image_id, category_id = ann.get("image_id"), ann.get("category_id")
        if type(image_id) is not int or image_id not in image_ids:
            raise ValueError("COCO 标注引用了不存在的 image_id")
        if type(category_id) is not int or category_id not in class_map:
            raise ValueError("COCO 标注引用了不存在的 category_id")
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


def _geometry(annotation: dict, task: CocoTask) -> dict:
    if task == "detect":
        bbox = annotation.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4 or any(type(value) not in (int, float) for value in bbox):
            raise ValueError("COCO 检测标注须包含 bbox [x, y, width, height]")
        return {"type": "bbox", "bbox": dict(zip(("x", "y", "width", "height"), bbox))}
    segmentation = annotation.get("segmentation")
    if annotation.get("iscrowd") or isinstance(segmentation, dict):
        raise ValueError("实例分割导入需要多边形，当前不能导入 RLE 或 crowd 掩码")
    if not isinstance(segmentation, list) or len(segmentation) != 1:
        raise ValueError("实例分割导入要求每个对象包含一个多边形轮廓")
    coords = segmentation[0]
    if (not isinstance(coords, list) or len(coords) < 6 or len(coords) % 2
            or any(type(value) not in (int, float) for value in coords)):
        raise ValueError("COCO 多边形须包含至少三个坐标对")
    return {"type": "polygon", "polygon": list(zip(coords[::2], coords[1::2]))}


def _import_manifest(db: Session, dataset_id: str, task: CocoTask, doc: dict, manifest: PurePosixPath,
                     locate, bytes_at, classes: dict[str, str], saved_paths: list[str], seen: set[PurePosixPath]) -> None:
    class_map = _category_map(db, dataset_id, doc, classes)
    image_rows = _rows(doc, "images")
    ids = [row.get("id") for row in image_rows]
    if any(type(value) is not int for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("COCO 图片须有唯一整数 ID")
    grouped = _annotations_for_images(doc, set(ids), class_map)
    class_ids = set(class_map.values())
    split_hint = _split((manifest.stem,), manifest_name=True) or _split(tuple(reversed(manifest.parent.parts)))
    for row in image_rows:
        filename = row.get("file_name")
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("COCO 图片缺少 file_name")
        try:
            path = locate(filename, manifest, split_hint)
            split = _split(tuple(reversed(path.parent.parts)))
            if split and split_hint and split != split_hint:
                raise ValueError("图片目录与标注文件的分集不一致")
            if path in seen:
                raise ValueError("同一图片出现在多个 COCO 记录中")
            seen.add(path)
            stored = save_image(bytes_at(path, MAX_IMAGE_BYTES))
            saved_paths.append(stored.path)
            if ((row.get("width", stored.width), row.get("height", stored.height))
                    != (stored.width, stored.height)):
                raise ValueError("图片尺寸与 COCO JSON 中记录的尺寸不一致")
            annotations = [{"id": str(uuid4()), "class_id": class_map[ann["category_id"]],
                            "source": "imported", **_geometry(ann, task)} for ann in grouped.get(row["id"], [])]
            status = "annotated" if annotations else "negative" if "annotations" in doc else "unlabeled"
            validated = validate_annotations(task_type=task, width=stored.width, height=stored.height, keypoint_names=[],
                                             class_ids=class_ids, status=status, annotations=annotations)
            repository.add_image(db, dataset_id, path.name, stored.width, stored.height, split_hint or split,
                                 stored.path, status=status, annotations=validated)
            if len(saved_paths) % 500 == 0:
                db.flush()
        except (OSError, ValueError) as exc:
            raise ValueError(f"{filename}：{exc}") from exc


def _import_coco(db: Session, name: str, task: CocoTask, files: Collection[PurePosixPath],
                 bytes_at: Callable[[PurePosixPath, int], bytes]) -> schemas.DatasetResponse:
    images = {path for path in files if path.suffix.lower() in IMAGE_EXTENSIONS}
    by_name = defaultdict(list)
    for path in images:
        by_name[path.name].append(path)
    classes: dict[str, str] = {}
    saved_paths: list[str] = []
    seen: set[PurePosixPath] = set()

    def locate(filename: str, manifest: PurePosixPath, split: str | None) -> PurePosixPath:
        return _find_image(filename, manifest, images, by_name, split)

    try:
        dataset = repository.create_dataset(db, name, task)
        for manifest in _manifest_paths(files):
            doc = _read_manifest(manifest, bytes_at)
            if doc is None:
                continue
            try:
                _import_manifest(db, dataset.id, task, doc, manifest, locate, bytes_at, classes, saved_paths, seen)
            except ValueError as exc:
                raise ValueError(f"{manifest}：{exc}") from exc
            del doc
        if not seen:
            raise ValueError("没有找到包含可导入图片的 COCO JSON")
        response = repository.serialize(dataset)
        db.commit()
        return response
    except Exception:
        db.rollback()
        remove_images(saved_paths)
        raise


def import_coco_archive(db: Session, source: BinaryIO, filename: str, task: CocoTask) -> schemas.DatasetResponse:
    if source.seek(0, 2) > MAX_ARCHIVE_BYTES:
        raise ValueError("ZIP 文件不能超过 256 MiB")
    source.seek(0)
    name = Path(filename.replace("\\", "/")).stem[:120] or "COCO 数据集"
    try:
        with ZipFile(source) as archive:
            files = inspect_members(archive)

            def bytes_at(path: PurePosixPath, limit: int) -> bytes:
                return read_bytes(archive, files[path], limit)

            return _import_coco(db, name, task, files, bytes_at)
    except (BadZipFile, NotImplementedError, EOFError) as exc:
        raise ValueError("无法读取 ZIP 或不支持此压缩方式") from exc


def import_coco_directory(db: Session, folder: str, task: CocoTask) -> schemas.DatasetResponse:
    root = directory_root(folder)
    files = directory_members(root, extra_suffixes=frozenset({".json"}))
    return _import_coco(db, root.name[:120], task, files, partial(read_directory_file, root))
