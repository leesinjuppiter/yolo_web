from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile

import pytest
from sqlalchemy.orm import Session

from app.core.database import engine
from app.training.models import TrainingTask
from app.training.repository import task_dir
from test_training_api import client, ready_dataset, task_ids, _config, _create


@pytest.fixture
def archived_task(client, ready_dataset, task_ids):
    task = _create(client, _config(ready_dataset["id"]), task_ids)
    root = task_dir(task["id"])
    files = {"output/weights/best.pt": b"checkpoint", "output/results.csv": b"epoch,loss\n1,0.5\n",
             "training.log": "训练完成\n".encode()}
    artifacts = []
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        artifacts.append({"id": relative.replace("/", "-"), "name": path.name, "path": relative,
                          "kind": "report", "sha256": sha256(content).hexdigest(), "sizeBytes": len(content)})
    (root / "not-registered.txt").write_text("must not be included")
    with Session(engine()) as db, db.begin():
        row = db.get(TrainingTask, task["id"])
        row.status, row.artifacts = "succeeded", artifacts
    return task["id"], root, files


def test_download_zip_contains_only_registered_files(client, archived_task):
    task_id, _, files = archived_task
    response = client.get(f"/api/training/{task_id}/artifacts/download.zip")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert f'training-{task_id}-artifacts.zip' in response.headers["content-disposition"]
    with ZipFile(BytesIO(response.content)) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == set(files)
        assert {name: archive.read(name) for name in archive.namelist()} == files


@pytest.mark.parametrize("problem, expected", [("changed", 409), ("missing", 404), ("outside", 404),
                                              ("running", 409), ("empty", 404)])
def test_download_zip_rejects_incomplete_or_unsafe_artifacts(client, archived_task, problem, expected):
    task_id, root, _ = archived_task
    if problem == "changed":
        (root / "training.log").write_bytes(b"modified")
    elif problem == "missing":
        (root / "training.log").unlink()
    else:
        with Session(engine()) as db, db.begin():
            row = db.get(TrainingTask, task_id)
            if problem == "running":
                row.status = "running"
            elif problem == "empty":
                row.artifacts = []
            else:
                outside = root.parent / "outside.txt"
                outside.write_bytes(b"secret")
                row.artifacts = [{**row.artifacts[0], "path": "../outside.txt"}]
    response = client.get(f"/api/training/{task_id}/artifacts/download.zip")
    assert response.status_code == expected, response.text
