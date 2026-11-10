from math import cos, radians, sin

from pydantic import TypeAdapter, ValidationError

from app.annotation.schemas import Annotation, BoundingBox, OrientedBox, Polygon, Pose, Rectangle
from app.dataset.schemas import TASK_ANNOTATION

_annotation_adapter = TypeAdapter(Annotation)
_TOLERANCE = 0.5


def _bbox_points(box: Rectangle) -> list[tuple[float, float]]:
    return [(box.x, box.y), (box.x + box.width, box.y + box.height)]


def _obb_points(box: OrientedBox) -> list[tuple[float, float]]:
    shape = box.obb
    angle = radians(shape.angle % 360)
    dx, dy = shape.width / 2, shape.height / 2
    return [
        (shape.cx + x * cos(angle) - y * sin(angle), shape.cy + x * sin(angle) + y * cos(angle))
        for x, y in [(-dx, -dy), (dx, -dy), (dx, dy), (-dx, dy)]
    ]


def _polygon_points(shape: Polygon) -> list[tuple[float, float]]:
    points = shape.polygon
    area_twice = sum(
        x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1])
    )
    if len(set(points)) < 3 or abs(area_twice) < 1e-6:
        raise ValueError("多边形必须有至少三个不同顶点且面积大于零")
    return points


def _check_geometry(annotation: Annotation, width: int, height: int, keypoint_names: list[str]) -> None:
    points: list[tuple[float, float]] = []
    if isinstance(annotation, BoundingBox):
        points = _bbox_points(annotation.bbox)
    elif isinstance(annotation, OrientedBox):
        points = _obb_points(annotation)
    elif isinstance(annotation, Polygon):
        points = _polygon_points(annotation)
    elif isinstance(annotation, Pose):
        if [point.name for point in annotation.keypoints] != keypoint_names:
            raise ValueError("姿态标注关键点必须与数据集定义的名称和顺序一致")
        points = _bbox_points(annotation.bbox) + [(point.x, point.y) for point in annotation.keypoints]
    if any(not (-_TOLERANCE <= x <= width + _TOLERANCE and -_TOLERANCE <= y <= height + _TOLERANCE)
           for x, y in points):
        raise ValueError("标注坐标超出原始图片边界")


def validate_annotations(
    *,
    task_type: str,
    width: int,
    height: int,
    keypoint_names: list[str],
    class_ids: set[str],
    status: str,
    annotations: list[Annotation | dict],
    serialize: bool = True,
) -> list[dict]:
    if status not in {"unlabeled", "negative", "annotated"}:
        raise ValueError("图片标注状态无效")
    if bool(annotations) != (status == "annotated"):
        raise ValueError("已标注图片必须包含标注，未标注和负样本必须没有标注")
    if task_type == "classify" and (len(annotations) > 1 or status == "negative"):
        raise ValueError("图像分类每张图只允许一个类别，且不能设为负样本")

    clean = []
    seen_ids = set()
    for value in annotations:
        try:
            annotation = _annotation_adapter.validate_python(value)
        except ValidationError as error:
            raise ValueError("标注字段缺失或数据类型无效") from error
        if annotation.type != TASK_ANNOTATION.get(task_type):
            raise ValueError("标注类型与数据集任务不匹配")
        if str(annotation.class_id) not in class_ids:
            raise ValueError("标注引用了不存在的类别")
        if annotation.id in seen_ids:
            raise ValueError("同一图片中的标注 ID 必须唯一")
        _check_geometry(annotation, width, height, keypoint_names)
        seen_ids.add(annotation.id)
        if serialize:
            clean.append(annotation.model_dump(mode="json", exclude={"class_index"}))
    return clean
