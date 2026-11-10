import json
from io import BytesIO
from zipfile import ZipFile

import pytest

from app.dataset.exchange.archive import MAX_ARCHIVE_BYTES
from app.dataset.exchange.coco import import_coco_archive
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


@pytest.mark.parametrize("invalid", ["rle", "multipart", "path"])
def test_invalid_coco_directory_rolls_back_copied_images(client, tmp_path, invalid):
    root = tmp_path / "invalid COCO"
    root.mkdir()
    doc = _manifest()
    doc["images"].append({"id": 12, "file_name": "second.png"})
    doc["annotations"].append({**doc["annotations"][0], "id": 10, "image_id": 12})
    if invalid == "rle":
        doc["annotations"][-1]["segmentation"] = {"size": [80, 100], "counts": [1, 3]}
    elif invalid == "multipart":
        doc["annotations"][-1]["segmentation"] *= 2
    else:
        doc["images"][-1]["file_name"] = "../outside.png"
    (root / "annotations.json").write_text(json.dumps(doc), encoding="utf-8")
    for name in ("frame.png", "second.png"):
        (root / name).write_bytes(_png())
    before = client.get("/api/datasets").json()
    response = _local_request(client, "POST", "/api/datasets/import/coco-directory",
                              json={"path": str(root), "task_type": "segment"})
    assert response.status_code == 422, response.text
    assert {"rle": "RLE", "multipart": "一个多边形", "path": "不安全"}[invalid] in response.json()["detail"]
    assert client.get("/api/datasets").json() == before
    assert list((tmp_path / "images").glob("*")) == []


def test_coco_upload_checks_size_before_opening_zip():
    class OversizedArchive(BytesIO):
        def seek(self, offset, whence=0):
            assert (offset, whence) == (0, 2)
            return MAX_ARCHIVE_BYTES + 1

    with pytest.raises(ValueError, match="256 MiB"):
        import_coco_archive(None, OversizedArchive(), "large.zip", "detect")
