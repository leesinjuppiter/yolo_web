import os
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import event

from app.core.config import database_url
from app.core.database import engine
from app.main import app


@pytest.fixture
def client(monkeypatch, tmp_path):
    url = os.environ.get("WORKBENCH_TEST_DATABASE_URL")
    if not url:
        pytest.skip("需要一个已迁移的独立 PostgreSQL 测试库")
    monkeypatch.setenv("WORKBENCH_DATABASE_URL", url)
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path))
    from app.core.config import data_dir
    for cached in (database_url, data_dir, engine):
        cached.cache_clear()
    with TestClient(app) as test_client:
        yield test_client
    if engine.cache_info().currsize:
        engine().dispose()
    for cached in (database_url, data_dir, engine):
        cached.cache_clear()


@pytest.fixture
def dataset_url(client):
    response = client.post("/api/datasets", json={"name": f"test {uuid4()}", "task_type": "obb"})
    assert response.status_code == 201, response.text
    url = f"/api/datasets/{response.json()['id']}"
    yield url
    assert client.delete(url).status_code in {204, 404}


def _png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (100, 80), color="#b4c0cd").save(output, format="PNG")
    return output.getvalue()


def _upload(client, url):
    response = client.post(url + "/images", files={"files": ("frame.png", _png(), "image/png")})
    assert response.status_code == 200, response.text
    return response.json()["images"][0]


def test_save_split_and_negative_status_survive_reload(client, dataset_url):
    image = _upload(client, dataset_url)
    assert image["split"] is None
    assert image["status"] == "unlabeled"
    assert image["version"] == 0
    assert client.get(image["url"]).content == _png()

    response = client.patch(dataset_url + "/splits", json={"splits": {image["id"]: "test"}})
    assert response.status_code == 200, response.text
    assert response.json()["images"][0]["split"] == "test"

    response = client.put(
        f"{dataset_url}/images/{image['id']}/annotations",
        json={"version": 0, "status": "negative", "classes": [], "annotations": []},
    )
    assert response.status_code == 200, response.text
    latest = client.get(dataset_url).json()["images"][0]
    assert (latest["split"], latest["status"], latest["version"]) == ("test", "negative", 1)


def test_delete_image_removes_its_annotations_and_file_only(client, dataset_url, tmp_path):
    upload = client.post(dataset_url + "/images", files=[
        ("files", ("remove.png", _png(), "image/png")),
        ("files", ("keep.png", _png(), "image/png")),
    ])
    assert upload.status_code == 200, upload.text
    images = {item["name"]: item for item in upload.json()["images"]}
    target, remaining = images["remove.png"], images["keep.png"]
    url = f"{dataset_url}/images/{target['id']}"
    category = {"id": str(uuid4()), "name": "coal", "color": "#135791"}
    save = client.put(url + "/annotations", json={
        "version": 0, "status": "annotated", "classes": [category],
        "annotations": [{
            "id": str(uuid4()), "type": "obb", "class_id": category["id"],
            "obb": {"cx": 50, "cy": 40, "width": 20, "height": 10, "angle": 20},
        }],
    })
    assert save.status_code == 200, save.text
    assert len(list((tmp_path / "images").iterdir())) == 2
    assert client.delete(url).status_code == 204
    assert client.get(target["url"]).status_code == 404
    assert client.get(remaining["url"]).content == _png()
    assert len(list((tmp_path / "images").iterdir())) == 1
    latest = client.get(dataset_url).json()
    assert latest["images"] == [remaining]
    assert latest["classes"] == [{**category, "index": 0}]


def test_concurrent_save_with_same_version_only_accepts_one(client, dataset_url):
    image = _upload(client, dataset_url)
    url = f"{dataset_url}/images/{image['id']}/annotations"

    def submit(label_name):
        class_id = str(uuid4())
        return client.put(url, json={
            "version": 0, "status": "annotated",
            "classes": [{"id": class_id, "name": label_name, "color": "#135791"}],
            "annotations": [{
                "id": str(uuid4()), "type": "obb", "class_id": class_id, "source": "manual",
                "obb": {"cx": 50, "cy": 40, "width": 20, "height": 10, "angle": 20},
            }],
        })

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(submit, ["coal", "gangue"]))
    assert sorted(response.status_code for response in responses) == [200, 409]
    latest = client.get(dataset_url).json()
    assert len(latest["classes"]) == 1
    assert latest["images"][0]["version"] == 1
    assert latest["images"][0]["annotations"][0]["class_index"] == 0


def test_update_class_preserves_annotations_and_rejects_conflicts(client, dataset_url):
    image = _upload(client, dataset_url)
    first = {"id": str(uuid4()), "name": "coal", "color": "#135791"}
    second = {"id": str(uuid4()), "name": "gangue", "color": "#124512"}
    annotation = {
        "id": str(uuid4()), "type": "obb", "class_id": first["id"],
        "obb": {"cx": 50, "cy": 40, "width": 20, "height": 10, "angle": 20},
    }
    saved = client.put(f"{dataset_url}/images/{image['id']}/annotations", json={
        "version": 0, "status": "annotated", "classes": [first, second], "annotations": [annotation],
    })
    assert saved.status_code == 200, saved.text
    url = f"{dataset_url}/classes/{first['id']}"
    previous = {"name": first["name"], "color": first["color"]}
    update = {"name": "煤", "color": "#AABBCC", "previous": previous}
    assert client.patch(url, json={**update, "name": " GANGUE "}).status_code == 409
    assert client.patch(url, json={**update, "color": "blue"}).status_code == 422
    response = client.patch(url, json=update)
    assert response.status_code == 200, response.text
    assert response.json() == {"id": first["id"], "name": "煤", "color": "#aabbcc", "index": 0}
    assert client.patch(url, json=update).status_code == 409
    latest = client.get(dataset_url).json()
    assert latest["classes"][0] == response.json()
    assert latest["images"] == saved.json()["images"]


def test_upload_invalid_second_file_rolls_back_first(client, dataset_url, tmp_path):
    response = client.post(dataset_url + "/images", files=[
        ("files", ("valid.png", _png(), "image/png")),
        ("files", ("invalid.png", b"bad bytes", "image/png")),
    ])
    assert response.status_code == 422, response.text
    assert client.get(dataset_url).json()["images"] == []
    assert not list((tmp_path / "images").glob("*"))


def test_dataset_read_sees_consistent_classes_and_annotations_during_save(client, dataset_url):
    image = _upload(client, dataset_url)
    classes_read, save_finished = Event(), Event()
    test_engine = engine()
    class_id = str(uuid4())

    def pause_read(_connection, _cursor, statement, *_):
        if "FROM dataset_classes" in statement and not classes_read.is_set():
            classes_read.set()
            if not save_finished.wait(timeout=5):
                raise TimeoutError("annotation write did not finish")

    event.listen(test_engine, "after_cursor_execute", pause_read)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            reading = pool.submit(client.get, dataset_url)
            try:
                assert classes_read.wait(timeout=5)
                saved = client.put(f"{dataset_url}/images/{image['id']}/annotations", json={
                    "version": 0, "status": "annotated",
                    "classes": [{"id": class_id, "name": "coal", "color": "#135791"}],
                    "annotations": [{
                        "id": str(uuid4()), "type": "obb", "class_id": class_id, "source": "manual",
                        "obb": {"cx": 50, "cy": 40, "width": 20, "height": 10, "angle": 20},
                    }],
                })
            finally:
                save_finished.set()
            assert saved.status_code == 200, saved.text
            before = reading.result(timeout=5).json()
            assert before["classes"] == []
            assert before["images"][0]["annotations"] == []
    finally:
        event.remove(test_engine, "after_cursor_execute", pause_read)
