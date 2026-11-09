from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image

from app.annotation.validation import validate_annotations
from app.core import storage


@pytest.mark.parametrize(
    ("task", "annotation", "keypoints"),
    [
        ("detect", {"type": "bbox", "bbox": {"x": 10, "y": 10, "width": 20, "height": 30}}, []),
        ("segment", {"type": "polygon", "polygon": [[10, 10], [60, 20], [30, 70]]}, []),
        ("obb", {"type": "obb", "obb": {"cx": 50, "cy": 50, "width": 20, "height": 30, "angle": 30}}, []),
        ("pose", {"type": "pose", "bbox": {"x": 10, "y": 10, "width": 20, "height": 30},
                  "keypoints": [{"name": "nose", "x": 20, "y": 20, "visible": 2}]}, ["nose"]),
        ("classify", {"type": "classify"}, []),
    ],
)
def test_five_annotation_types_preserve_original_pixel_coordinates(task, annotation, keypoints):
    class_id, annotation_id = str(uuid4()), str(uuid4())
    data = {**annotation, "id": annotation_id, "class_id": class_id, "source": "manual"}
    saved = validate_annotations(
        task_type=task, width=100, height=100, keypoint_names=keypoints,
        class_ids={class_id}, status="annotated", annotations=[data],
    )
    assert saved == [data]


def test_rotated_corners_cannot_extend_beyond_original_image():
    class_id = str(uuid4())
    value = {
        "type": "obb", "id": str(uuid4()), "class_id": class_id,
        "obb": {"cx": 10, "cy": 10, "width": 19, "height": 19, "angle": 45},
    }
    with pytest.raises(ValueError, match="图片边界"):
        validate_annotations(
            task_type="obb", width=100, height=100, keypoint_names=[],
            class_ids={class_id}, status="annotated", annotations=[value],
        )


def test_classify_allows_only_one_label():
    class_id = str(uuid4())
    values = [{"type": "classify", "id": str(uuid4()), "class_id": class_id} for _ in range(2)]
    with pytest.raises(ValueError, match="一个类别"):
        validate_annotations(
            task_type="classify", width=100, height=100, keypoint_names=[],
            class_ids={class_id}, status="annotated", annotations=values,
        )


def test_storage_normalizes_exif_without_changing_regular_images(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "data_dir", lambda: tmp_path)
    regular = BytesIO()
    rotated = BytesIO()
    source = Image.new("RGB", (100, 60))
    source.save(regular, format="PNG")
    exif = source.getexif()
    exif[274] = 6
    source.save(rotated, format="JPEG", exif=exif)

    first = storage.save_image(regular.getvalue())
    assert (first.width, first.height) == (100, 60)
    assert storage.resolve_image(first.path).read_bytes() == regular.getvalue()

    second = storage.save_image(rotated.getvalue())
    assert (second.width, second.height) == (60, 100)
    with Image.open(storage.resolve_image(second.path)) as canonical:
        assert canonical.size == (60, 100)
        assert canonical.getexif().get(274, 1) == 1
