import json
from io import BytesIO
from zipfile import ZipFile

import pytest

from app.dataset.exchange.archive import MAX_ARCHIVE_BYTES
from app.dataset.exchange.coco import _segmentation_polygon, import_coco_archive
from app.yolo import to_yolo
from test_yolo_exchange import _local_request, _png, client


def _manifest(category_id=17, *, annotations=True):
    doc = {"images": [{"id": 11, "file_name": "frame.png", "width": 100, "height": 80}]}
    if annotations:
        doc["categories"] = [{"id": category_id, "name": "煤"}]
        doc["annotations"] = [{
            "id": 9, "image_id": 11, "category_id": category_id,
            "bbox": [10, 12, 30, 20],
            "segmentation": [[10, 12, 40, 12, 40, 32, 10, 32]],
        }]
    return doc


def test_import_coco_zip_preserves_split_and_maps_sparse_categories(client):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for directory, manifest, doc in (
            ("train2017", "instances_train2017.json", _manifest()),
            ("val2017", "instances_val2017.json", _manifest(61)),
            ("test2017", "image_info_test2017.json", _manifest(annotations=False)),
        ):
            archive.writestr(f"coco/{directory}/frame.png", _png())
            archive.writestr(f"coco/annotations/{manifest}", json.dumps(doc))
    response = client.post("/api/datasets/import/coco",
                           files={"file": ("dataset.zip", buffer.getvalue())}, data={"task_type": "detect"})
    assert response.status_code == 201, response.text
    data = response.json()
    try:
        assert len(data["classes"]) == 1
        assert data["classes"][0]["name"] == "煤"
        images = {image["split"]: image for image in data["images"]}
        assert set(images) == {"train", "val", "test"}
        assert images["test"]["status"] == "unlabeled"
        for split in ("train", "val"):
            box = images[split]["annotations"][0]
            assert box["source"] == "imported"
            assert box["class_id"] == data["classes"][0]["id"]
            assert box["bbox"] == {"x": 10, "y": 12, "width": 30, "height": 20}
    finally:
        client.delete(f"/api/datasets/{data['id']}")


def test_import_coco_directory_preserves_polygon(client, tmp_path):
    root = tmp_path / "本地 COCO"
    val = root / "valid"
    val.mkdir(parents=True)
    (val / "frame.png").write_bytes(_png())
    (val / "_annotations.coco.json").write_text(json.dumps(_manifest()), encoding="utf-8")
    response = _local_request(client, "POST", "/api/datasets/import/coco-directory",
                              json={"path": str(root), "task_type": "segment"})
    assert response.status_code == 201, response.text
    data = response.json()
    try:
        image = data["images"][0]
        assert image["split"] == "val"
        assert image["annotations"][0]["polygon"] == [[10, 12], [40, 12], [40, 32], [10, 32]]
        assert client.get(image["url"]).content == _png()
    finally:
        client.delete(f"/api/datasets/{data['id']}")
    assert (val / "frame.png").exists()


@pytest.mark.parametrize("source", ["directory", "zip"])
def test_coco_multipart_preserves_one_instance_and_all_filled_contours(client, tmp_path, source):
    doc = _manifest()
    doc["annotations"][0]["segmentation"] += [[70, 12, 70, 32, 90, 32, 90, 12], [55, 5, 56, 5]]
    files = {"COCOformat/test.json": json.dumps(doc).encode(), "JPEGImages/frame.png": _png()}
    if source == "directory":
        root = tmp_path / "COCO"
        for name, content in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        response = _local_request(client, "POST", "/api/datasets/import/coco-directory",
                                  json={"path": str(root), "task_type": "segment"})
    else:
        buffer = BytesIO()
        with ZipFile(buffer, "w") as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        response = client.post("/api/datasets/import/coco", files={"file": ("coco.zip", buffer.getvalue())},
                               data={"task_type": "segment"})

    assert response.status_code == 201, response.text
    data = response.json()
    try:
        image = data["images"][0]
        assert image["split"] == "test"
        assert data["skipped_samples"] == []
        polygon, = [annotation["polygon"] for annotation in image["annotations"]]
        assert polygon == [[10, 12], [40, 12], [70, 12], [90, 12], [90, 32], [70, 32],
                           [70, 12], [40, 12], [40, 32], [10, 32]]
        assert len(to_yolo(image["annotations"], "segment", 100, 80, {data["classes"][0]["id"]: 0}).splitlines()) == 1
    finally:
        client.delete(f"/api/datasets/{data['id']}")


def test_coco_removes_only_redundant_vertices_to_fit_polygon_limit():
    coords = [value for x in range(4822) for value in (x, 0)] + [4821, 10, 0, 10]
    assert _segmentation_polygon({"segmentation": [coords]}) == [(0, 0), (4821, 0), (4821, 10), (0, 10)]


@pytest.mark.parametrize("invalid", ["rle", "degenerate", "path"])
def test_invalid_coco_directory_rolls_back_copied_images(client, tmp_path, invalid):
    root = tmp_path / "invalid COCO"
    root.mkdir()
    doc = _manifest()
    doc["images"].append({"id": 12, "file_name": "second.png"})
    doc["annotations"].append({**doc["annotations"][0], "id": 10, "image_id": 12})
    if invalid == "rle":
        doc["annotations"][-1]["segmentation"] = {"size": [80, 100], "counts": [1, 3]}
    elif invalid == "degenerate":
        doc["annotations"][-1]["segmentation"] = [[10, 12, 40, 12], [55, 20, 60, 20]]
    else:
        doc["images"][-1]["file_name"] = "../outside.png"
    (root / "annotations.json").write_text(json.dumps(doc), encoding="utf-8")
    for name in ("frame.png", "second.png"):
        (root / name).write_bytes(_png())
    before = client.get("/api/datasets").json()
    response = _local_request(client, "POST", "/api/datasets/import/coco-directory",
                              json={"path": str(root), "task_type": "segment"})
    assert response.status_code == 422, response.text
    assert {"rle": "RLE", "degenerate": "面积大于零", "path": "不安全"}[invalid] in response.json()["detail"]
    assert client.get("/api/datasets").json() == before
    assert list((tmp_path / "images").glob("*")) == []


@pytest.mark.parametrize("source", ["directory", "zip"])
def test_coco_repair_skips_whole_samples_and_preserves_valid_images(client, tmp_path, source):
    doc = _manifest()
    doc["images"].extend([
        {"id": 12, "file_name": "malformed_polygon.png"},
        {"id": 13, "file_name": "oversized_polygon.png"},
        {"id": 14, "file_name": "wrong_size.png", "width": 99, "height": 80},
        {"id": 15, "file_name": "missing.png"},
    ])
    base = doc["annotations"][0]
    doc["annotations"].extend([
        {**base, "id": 10, "image_id": 12},
        {**base, "id": 11, "image_id": 12, "segmentation": [*base["segmentation"], [10, 12, 20]]},
        {**base, "id": 12, "image_id": 13, "segmentation": [[10, 12] * 4001]},
    ])
    files = {"train.json": json.dumps(doc).encode()}
    files.update({name: _png() for name in ("frame.png", "malformed_polygon.png", "oversized_polygon.png", "wrong_size.png")})
    if source == "directory":
        root = tmp_path / "COCO"
        root.mkdir()
        for name, content in files.items():
            (root / name).write_bytes(content)
        response = _local_request(client, "POST", "/api/datasets/import/coco-directory",
                                  json={"path": str(root), "task_type": "segment", "skip_invalid": True})
    else:
        buffer = BytesIO()
        with ZipFile(buffer, "w") as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        response = client.post("/api/datasets/import/coco", files={"file": ("coco.zip", buffer.getvalue())},
                               data={"task_type": "segment", "skip_invalid": "true"})

    assert response.status_code == 201, response.text
    data = response.json()
    try:
        assert [(image["name"], image["split"], image["status"]) for image in data["images"]] == [
            ("frame.png", "train", "annotated"),
        ]
        assert {sample["manifest"] for sample in data["skipped_samples"]} == {"train.json"}
        reasons = {sample["filename"]: sample["reason"] for sample in data["skipped_samples"]}
        assert len(reasons) == len(data["skipped_samples"]) == 4
        assert "坐标对" in reasons["malformed_polygon.png"]
        assert "超过 4000" in reasons["oversized_polygon.png"]
        assert "尺寸不一致" in reasons["wrong_size.png"]
        assert "找不到图片" in reasons["missing.png"]
        assert len(list((tmp_path / "images").iterdir())) == 1
        assert client.get(data["images"][0]["url"]).content == files["frame.png"]
    finally:
        client.delete(f"/api/datasets/{data['id']}")
    if source == "directory":
        assert {p.name: p.read_bytes() for p in root.iterdir()} == files


def test_coco_repair_rejects_an_empty_result(client, tmp_path):
    root = tmp_path / "COCO"
    root.mkdir()
    (root / "train.json").write_text(json.dumps(_manifest()), encoding="utf-8")
    before = client.get("/api/datasets").json()
    response = _local_request(client, "POST", "/api/datasets/import/coco-directory",
                              json={"path": str(root), "task_type": "segment", "skip_invalid": True})
    assert response.status_code == 422, response.text
    assert "已排除全部 1 个样本" in response.json()["detail"]
    assert client.get("/api/datasets").json() == before


def test_coco_upload_checks_size_before_opening_zip():
    class OversizedArchive(BytesIO):
        def seek(self, offset, whence=0):
            assert (offset, whence) == (0, 2)
            return MAX_ARCHIVE_BYTES + 1

    with pytest.raises(ValueError, match="256 MiB"):
        import_coco_archive(None, OversizedArchive(), "large.zip", "detect")
