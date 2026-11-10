import asyncio
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import httpx
import pytest
from PIL import Image

from app.dataset.exchange.archive import inspect_members
from app.yolo import from_yolo, to_yolo
from test_dataset_api import client


@pytest.mark.parametrize(("task", "kind", "geometry"), [
    ("detect", "bbox", {"bbox": {"x": 10, "y": 20, "width": 30, "height": 20}}),
    ("segment", "polygon", {"polygon": [[10, 10], [30, 10], [20, 40]]}),
    ("obb", "obb", {"obb": {"cx": 45, "cy": 35, "width": 20, "height": 10, "angle": 35}}),
    ("pose", "pose", {
        "bbox": {"x": 10, "y": 20, "width": 30, "height": 20},
        "keypoints": [{"name": "tip", "x": 25, "y": 30, "visible": 1}],
    }),
    ("classify", "classify", {}),
])
def test_geometry_round_trip(task, kind, geometry):
    annotation = {"type": kind, "class_id": "object", **geometry}
    names = ["tip"] if task == "pose" else []
    row = to_yolo([annotation], task, 110, 80, {"object": 0}, names)
    returned = from_yolo(row, task, 110, 80, ["object"], names)[0]
    repeated = to_yolo([returned], task, 110, 80, {"object": 0}, names)
    assert [float(value) for value in repeated.split()] == pytest.approx([float(value) for value in row.split()])
    assert returned["source"] == "imported"


def test_invalid_obb_and_nonfinite_values_are_rejected():
    with pytest.raises(ValueError, match="矩形"):
        from_yolo("0 .1 .1 .8 .1 .3 .2 .1 .7", "obb", 110, 80, ["object"])
    with pytest.raises(ValueError, match="坐标"):
        from_yolo("0 .5 .5 nan .1", "detect", 110, 80, ["object"])


@pytest.mark.parametrize("member", ["../escape.txt", "C:/escape.txt", "/escape.txt", r"..\escape.txt"])
def test_malicious_archive_member_is_rejected(member):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(member, "unsafe")
    with ZipFile(buffer) as archive:
        with pytest.raises(ValueError, match="不安全"):
            inspect_members(archive)


def _png():
    output = BytesIO()
    Image.new("RGB", (100, 80), color="#45505c").save(output, format="PNG")
    return output.getvalue()


def _archive(val_label: str) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("sample/data.yaml", "train: images/train\nval: images/val\nnames: [煤]\n")
        for split, name, label in (
            ("train", "coal", "0 .4 .4 .2 .2"),
            ("val", "coal", val_label),
            ("train", "empty", ""),
            ("train", "unlabeled", None),
        ):
            archive.writestr(f"sample/images/{split}/{name}.png", _png())
            if label is not None:
                archive.writestr(f"sample/labels/{split}/{name}.txt", label)
    return buffer.getvalue()


def _upload(client, archive):
    return client.post("/api/datasets/import/yolo",
                       files={"file": (f"{uuid4()}.zip", archive, "application/zip")},
                       data={"task_type": "detect"})


def test_zip_import_export_statuses_and_cross_split_report(client):
    response = _upload(client, _archive("0 .4 .4 .2 .2"))
    assert response.status_code == 201, response.text
    data = response.json()
    url = f"/api/datasets/{data['id']}"
    try:
        assert sorted(image["status"] for image in data["images"]) == ["annotated", "annotated", "negative", "unlabeled"]
        report = client.get(url + "/reports/validate").json()
        assert any(issue["code"] == "duplicate_across_splits" for issue in report["issues"])
        for include_negative, count in ((True, 3), (False, 2)):
            response = client.get(url + "/export/yolo", params={"include_negative": include_negative})
            assert response.status_code == 200, response.text
            with ZipFile(BytesIO(response.content)) as archive:
                images = [name for name in archive.namelist() if name.endswith(".png")]
                labels = [name for name in archive.namelist() if name.endswith(".txt")]
                assert len(images) == len(labels) == count
                assert all("unlabeled" not in name for name in images)
                assert sum(archive.read(name) == b"" for name in labels) == int(include_negative)
        labels_only = client.get(url + "/export/yolo", params={"include_images": False})
        with ZipFile(BytesIO(labels_only.content)) as archive:
            assert all(not name.endswith(".png") for name in archive.namelist())
    finally:
        client.delete(url)


def test_invalid_label_rolls_back_zip_import(client, tmp_path):
    before = len(client.get("/api/datasets").json())
    response = _upload(client, _archive("5 .4 .4 .2 .2"))
    assert response.status_code == 422, response.text
    assert len(client.get("/api/datasets").json()) == before
    assert list((tmp_path / "images").glob("*")) == []


def _local_request(client, method, path, **kwargs):
    async def send():
        transport = httpx.ASGITransport(app=client.app, client=("127.0.0.1", 50000))
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as local:
            return await local.request(method, path, **kwargs)

    return asyncio.run(send())


def test_directory_import_keeps_splits_and_labels(client, tmp_path):
    root = tmp_path / "本地样本"
    root.mkdir()
    (root / "data.yaml").write_text("train: images/train\nval: images/val\nnames: [煤]\n", encoding="utf-8")
    for split, label in (("train", "0 .4 .4 .2 .2"), ("val", "")):
        image = root / "images" / split / "sample.png"
        annotation = root / "labels" / split / "sample.txt"
        image.parent.mkdir(parents=True)
        annotation.parent.mkdir(parents=True)
        image.write_bytes(_png())
        annotation.write_text(label, encoding="utf-8")
    browse = _local_request(client, "GET", "/api/datasets/import/directories", params={"path": str(root)})
    assert browse.status_code == 200, browse.text
    assert {entry["name"] for entry in browse.json()["directories"]} == {"images", "labels"}
    response = _local_request(client, "POST", "/api/datasets/import/yolo-directory",
                              json={"path": str(root), "task_type": "detect"})
    assert response.status_code == 201, response.text
    data = response.json()
    try:
        assert data["name"] == root.name
        assert data["classes"][0]["name"] == "煤"
        images = {image["split"]: image for image in data["images"]}
        assert images["train"]["annotations"][0]["source"] == "imported"
        assert images["val"]["status"] == "negative"
        assert client.get(images["train"]["url"]).content == _png()
    finally:
        client.delete(f"/api/datasets/{data['id']}")
    assert (root / "images" / "train" / "sample.png").exists()


def test_local_directory_rejects_remote_requests_and_external_references(client, tmp_path):
    assert client.get("/api/datasets/import/directories").status_code == 403
    root = tmp_path / "outside-reference"
    root.mkdir()
    (root / "data.yaml").write_text("train: ../outside\nnames: [coal]\n", encoding="utf-8")
    response = _local_request(client, "POST", "/api/datasets/import/yolo-directory",
                              json={"path": str(root), "task_type": "detect"})
    assert response.status_code == 422
    assert "超出所选目录" in response.json()["detail"]


def test_invalid_local_label_rolls_back_copied_image(client, tmp_path):
    root = tmp_path / "invalid-directory"
    (root / "images" / "train").mkdir(parents=True)
    (root / "labels" / "train").mkdir(parents=True)
    (root / "data.yaml").write_text("names: [coal]\n", encoding="utf-8")
    (root / "images" / "train" / "sample.png").write_bytes(_png())
    (root / "labels" / "train" / "sample.txt").write_text("5 .4 .4 .2 .2", encoding="utf-8")
    before = len(client.get("/api/datasets").json())
    response = _local_request(client, "POST", "/api/datasets/import/yolo-directory",
                              json={"path": str(root), "task_type": "detect"})
    assert response.status_code == 422, response.text
    assert len(client.get("/api/datasets").json()) == before
    assert list((tmp_path / "images").glob("*")) == []
