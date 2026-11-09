"""Convert absolute-pixel annotations to and from YOLO rows."""

from collections.abc import Mapping, Sequence
from math import atan2, cos, degrees, hypot, isfinite, radians, sin
from uuid import uuid4

from app.dataset.schemas import TASK_ANNOTATION


def _coordinates(values: Sequence[float]) -> list[float]:
    if any(not isfinite(value) or value < -1e-8 or value > 1 + 1e-8 for value in values):
        raise ValueError("YOLO 坐标必须在 0 到 1 之间")
    return [min(1.0, max(0.0, value)) for value in values]


def _box_values(box: dict, width: int, height: int) -> list[float]:
    return [
        (box["x"] + box["width"] / 2) / width,
        (box["y"] + box["height"] / 2) / height,
        box["width"] / width,
        box["height"] / height,
    ]


def _absolute_box(values: Sequence[float], width: int, height: int) -> dict:
    x, y, w, h = _coordinates(values)
    return {"x": (x - w / 2) * width, "y": (y - h / 2) * height,
            "width": w * width, "height": h * height}


def _corners(box: dict) -> list[tuple[float, float]]:
    angle = radians(box["angle"] % 360)
    c, s = cos(angle), sin(angle)
    w, h = box["width"] / 2, box["height"] / 2
    return [(box["cx"] + x * c - y * s, box["cy"] + x * s + y * c)
            for x, y in [(-w, -h), (w, -h), (w, h), (-w, h)]]


def _absolute_obb(points: Sequence[tuple[float, float]]) -> dict:
    a, b, c, d = points
    dx, dy = b[0] - a[0], b[1] - a[1]
    hx, hy = d[0] - a[0], d[1] - a[1]
    width, height = hypot(dx, dy), hypot(hx, hy)
    tolerance = 0.02 + min(width, height) * 0.001
    if (not width or not height or abs(dx * hx + dy * hy) / max(width, height) > tolerance
            or hypot(b[0] + hx - c[0], b[1] + hy - c[1]) > tolerance):
        raise ValueError("YOLO OBB 的四个顶点须按顺序组成矩形")
    return {"cx": (a[0] + c[0]) / 2, "cy": (a[1] + c[1]) / 2,
            "width": width, "height": height, "angle": degrees(atan2(dy, dx))}


def _encode(annotation: dict, width: int, height: int, keypoint_names: Sequence[str]) -> list[float | int]:
    kind = annotation["type"]
    if kind == "classify":
        return []
    if kind == "bbox":
        return _coordinates(_box_values(annotation["bbox"], width, height))
    if kind in ("obb", "polygon"):
        points = _corners(annotation["obb"]) if kind == "obb" else annotation["polygon"]
        return _coordinates([value for x, y in points for value in (x / width, y / height)])

    points = {point["name"]: point for point in annotation["keypoints"]}
    if set(points) != set(keypoint_names) or len(annotation["keypoints"]) != len(points):
        raise ValueError("关键点与数据集关键点定义不匹配")
    values: list[float | int] = _coordinates(_box_values(annotation["bbox"], width, height))
    for name in keypoint_names:
        point = points[name]
        visibility = point["visible"]
        if visibility not in (0, 1, 2):
            raise ValueError("关键点可见性须为 0、1 或 2")
        values.extend([*_coordinates([point["x"] / width, point["y"] / height]), visibility])
    return values


def to_yolo(annotations: Sequence[dict], task_type: str, width: int, height: int,
            class_indices: Mapping[str, int], keypoint_names: Sequence[str] = ()) -> str:
    kind = TASK_ANNOTATION.get(task_type)
    if not kind or width <= 0 or height <= 0:
        raise ValueError("无效的任务类型或图片尺寸")
    rows = []
    for annotation in annotations:
        if annotation["type"] != kind or annotation["class_id"] not in class_indices:
            raise ValueError("标注类型或类别与数据集不匹配")
        tokens = [str(class_indices[annotation["class_id"]])]
        tokens.extend(format(value, ".10g") for value in _encode(annotation, width, height, keypoint_names))
        rows.append(" ".join(tokens) + "\n")
    return "".join(rows)


def _decode(kind: str, values: Sequence[float], width: int, height: int,
            keypoint_names: Sequence[str], kpt_dims: int) -> dict:
    if kind == "classify" and not values:
        return {}
    if kind == "bbox" and len(values) == 4:
        return {"bbox": _absolute_box(values, width, height)}
    if (kind == "polygon" and len(values) >= 6 and len(values) % 2 == 0) or (kind == "obb" and len(values) == 8):
        coordinates = _coordinates(values)
        points = list(zip((x * width for x in coordinates[::2]), (y * height for y in coordinates[1::2])))
        return {"obb": _absolute_obb(points)} if kind == "obb" else {"polygon": [list(point) for point in points]}
    if kind == "pose" and keypoint_names and kpt_dims in (2, 3) and len(values) == 4 + len(keypoint_names) * kpt_dims:
        keypoints = []
        for index, name in enumerate(keypoint_names):
            start = 4 + index * kpt_dims
            x, y = _coordinates(values[start:start + 2])
            visible = values[start + 2] if kpt_dims == 3 else 2
            if visible not in (0, 1, 2):
                raise ValueError("关键点可见性须为 0、1 或 2")
            keypoints.append({"name": name, "x": x * width, "y": y * height, "visible": int(visible)})
        return {"bbox": _absolute_box(values[:4], width, height), "keypoints": keypoints}
    raise ValueError("标注列数不符合任务格式")


def from_yolo(text: str, task_type: str, width: int, height: int, class_ids: Sequence[str],
              keypoint_names: Sequence[str] = (), kpt_dims: int = 3) -> list[dict]:
    kind = TASK_ANNOTATION.get(task_type)
    if not kind or width <= 0 or height <= 0:
        raise ValueError("无效的任务类型或图片尺寸")
    annotations = []
    for line_number, row in enumerate(text.splitlines(), 1):
        if not row.strip():
            continue
        tokens = row.split()
        try:
            index = int(tokens[0])
            if not 0 <= index < len(class_ids):
                raise ValueError("类别编号超出范围")
            values = [float(token) for token in tokens[1:]]
            geometry = _decode(kind, values, width, height, keypoint_names, kpt_dims)
        except ValueError as exc:
            raise ValueError(f"标注第 {line_number} 行：{exc}") from exc
        annotations.append({"id": uuid4().hex, "type": kind, "class_id": class_ids[index],
                            "source": "imported", **geometry})
    return annotations
