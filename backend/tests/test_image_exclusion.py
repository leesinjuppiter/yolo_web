from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

from sqlalchemy.orm import Session

from app.core.database import engine
from app.dataset import repository, service
from test_dataset_api import _png, _upload, client, dataset_url


def test_excluded_sample_is_restorable_and_removed_from_active_operations(client, dataset_url):
    dataset_id = dataset_url.rsplit("/", 1)[-1]
    category = {"id": str(uuid4()), "name": "coal", "color": "#135791"}
    images = []
    for name, split in [("excluded.png", "train"), ("train.png", "train"), ("val.png", "val")]:
        upload = client.post(dataset_url + "/images", data={"split": split},
                             files={"files": (name, _png(), "image/png")})
        assert upload.status_code == 200, upload.text
        image = next(item for item in upload.json()["images"] if item["name"] == name)
        save = client.put(f"{dataset_url}/images/{image['id']}/annotations?compact=true", json={
            "version": 0, "status": "annotated", "classes": [category],
            "annotations": [{
                "id": str(uuid4()), "type": "obb", "class_id": category["id"],
                "obb": {"cx": 50, "cy": 40, "width": 20, "height": 10, "angle": 20},
            }],
        })
        assert save.status_code == 200, save.text
        images.append(save.json()["image"])

    target = images[0]
    image_id = target["id"]
    with Session(engine()) as db:
        dataset = repository.get_dataset(db, dataset_id, lock=True)
        service.exclude_image(db, dataset_id, image_id)
        assert image_id not in {image.id for image in dataset.images}
        db.rollback()
    assert len(client.get(dataset_url).json()["images"]) == 3
    with Session(engine()) as db, db.begin():
        service.exclude_image(db, dataset_id, image_id)

    latest = client.get(dataset_url).json()
    assert {image["id"] for image in latest["images"]} == {image["id"] for image in images[1:]}
    assert client.get(target["url"]).content == _png()
    assert client.patch(dataset_url + "/splits", json={"splits": {image_id: "test"}}).status_code == 404
    assert client.put(f"{dataset_url}/images/{image_id}/annotations", json={
        "version": target["version"], "status": "negative", "classes": [], "annotations": [],
    }).status_code == 404

    quality = client.get(dataset_url + "/reports/quality").json()
    assert quality["class_counts"] == {category["id"]: 2}
    duplicates = client.get(dataset_url + "/reports/duplicates").json()
    assert next(item["value"] for item in duplicates["items"] if item["label"] == "分析图片") == 2
    validation = client.get(dataset_url + "/reports/validate").json()
    assert all(issue["image_id"] != image_id and issue["related_image_id"] != image_id
               for issue in validation["issues"])
    export = client.get(dataset_url + "/export/yolo")
    assert export.status_code == 200, export.text
    with ZipFile(BytesIO(export.content)) as archive:
        assert not any(image_id in member for member in archive.namelist())
        assert all(any(image["id"] in member for member in archive.namelist()) for image in images[1:])

    with Session(engine()) as db:
        [excluded] = service.list_excluded_images(db, dataset_id)
        assert excluded.excluded_at is not None
        assert excluded.model_dump(mode="json")["annotations"] == target["annotations"]
    with Session(engine()) as db:
        restored = service.restore_excluded_image(db, dataset_id, image_id)
        assert restored.excluded_at is None
        assert restored.split == target["split"]
        assert restored.version == target["version"] + 2
        assert restored.model_dump(mode="json")["annotations"] == target["annotations"]
    assert len(client.get(dataset_url).json()["images"]) == 3


def test_deleting_dataset_also_cleans_excluded_image_file(client, dataset_url, tmp_path):
    image = _upload(client, dataset_url)
    with Session(engine()) as db, db.begin():
        service.exclude_image(db, dataset_url.rsplit("/", 1)[-1], image["id"])
    assert list((tmp_path / "images").iterdir())
    assert client.delete(dataset_url).status_code == 204
    assert not list((tmp_path / "images").iterdir())
