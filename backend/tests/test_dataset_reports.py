import os
from uuid import uuid4

from app.quality import fingerprints
from test_dataset_api import _png, client


def test_file_reports_reuse_facts_and_recheck_replaced_file(client, tmp_path, monkeypatch):
    dataset = client.post("/api/datasets", json={"name": "file report", "task_type": "detect"}).json()
    url = f"/api/datasets/{dataset['id']}"
    try:
        upload = client.post(url + "/images", files={"files": ("sample.png", _png(), "image/png")})
        assert upload.status_code == 200, upload.text
        path, = (tmp_path / "images").glob("*.png")
        decoded = []
        original = fingerprints.open_checked_image

        def count_decode(data):
            decoded.append(len(data))
            return original(data)

        monkeypatch.setattr(fingerprints, "open_checked_image", count_decode)
        validated = client.get(url + "/reports/validate").json()
        assert validated["items"][0] == {"label": "错误", "value": 0}
        duplicates = client.get(url + "/reports/duplicates").json()
        assert duplicates["items"][2] == {"label": "无效图片", "value": 0}
        assert len(decoded) == 1

        previous = path.stat()
        path.write_bytes(b"x" * previous.st_size)
        os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000_000))
        duplicates = client.get(url + "/reports/duplicates").json()
        assert duplicates["items"][2] == {"label": "无效图片", "value": 1}
        validated = client.get(url + "/reports/validate").json()
        assert any(issue["code"] == "image_invalid" for issue in validated["issues"])
        assert len(decoded) == 2

        path.unlink()
        validated = client.get(url + "/reports/validate").json()
        assert any("图片文件缺失" in issue["message"] for issue in validated["issues"])
    finally:
        client.delete(url)


def test_quality_report_counts_latest_saved_annotation_and_empty_classes(client):
    dataset = client.post("/api/datasets", json={"name": "quality report", "task_type": "detect"}).json()
    url = f"/api/datasets/{dataset['id']}"
    try:
        upload = client.post(url + "/images", files={"files": ("sample.png", _png(), "image/png")})
        assert upload.status_code == 200, upload.text
        image, = upload.json()["images"]
        classes = [{"id": str(uuid4()), "name": name, "color": "#135791"} for name in ("coal", "gangue")]
        target = f"{url}/images/{image['id']}/annotations?compact=true"
        save = client.put(target, json={"version": 0, "status": "annotated", "classes": classes, "annotations": [{
            "id": str(uuid4()), "type": "bbox", "class_id": classes[0]["id"],
            "bbox": {"x": 3, "y": 5, "width": 20, "height": 10},
        }]})
        assert save.status_code == 200, save.text
        quality = client.get(url + "/reports/quality").json()
        assert quality["class_counts"] == {classes[0]["id"]: 1, classes[1]["id"]: 0}
        assert quality["items"][-1] == {"label": "标注总数", "value": 1}
        save = client.put(target, json={"version": 1, "status": "negative", "classes": classes, "annotations": []})
        assert save.status_code == 200, save.text
        quality = client.get(url + "/reports/quality").json()
        assert quality["class_counts"] == {item["id"]: 0 for item in classes}
        assert quality["items"][2] == {"label": "负样本", "value": 1}
    finally:
        client.delete(url)
