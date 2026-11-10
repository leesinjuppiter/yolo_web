from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.database import engine
from app.dataset.analysis import worker
from app.dataset.analysis.models import DatasetAnalysisJob
from app.dataset.analysis.reporting import compute_report
from test_dataset_api import _png, client, dataset_url


def _snapshot(client, url, kind):
    response = client.get(f"{url}/reports/{kind}/snapshot")
    assert response.status_code == 200, response.text
    return response.json()


def _refresh(client, url, kind, *, force=False):
    response = client.post(f"{url}/reports/{kind}/refresh", json={"force": force})
    assert response.status_code == 202, response.text
    return response.json()


def _ready(client, url, kind):
    _refresh(client, url, kind)
    for _ in range(4):
        state = _snapshot(client, url, kind)
        if state["status"] == "ready":
            return state
        assert worker.process_next(compute_report)
    raise AssertionError(f"{kind} report did not finish")


def test_reports_refresh_only_for_relevant_dataset_changes(client, dataset_url):
    assert _snapshot(client, dataset_url, "quality")["status"] == "idle"
    for name, split in (("first.png", "train"), ("copy.png", "val")):
        result = client.post(dataset_url + "/images", data={"split": split},
                             files={"files": (name, _png(), "image/png")})
        assert result.status_code == 200, result.text
    first, copy = result.json()["images"]
    assert _snapshot(client, dataset_url, "validate")["status"] == "queued"

    quality = _ready(client, dataset_url, "quality")
    duplicates = _ready(client, dataset_url, "duplicates")
    validation = _ready(client, dataset_url, "validate")
    assert duplicates["report"]["items"][0]["value"] == 1
    assert duplicates["report"]["issues"][0]["related_image_id"] == first["id"]
    assert any(issue["code"] == "duplicate_across_splits" for issue in validation["report"]["issues"])

    save = client.put(f"{dataset_url}/images/{copy['id']}/annotations?compact=true",
                      json={"version": 0, "status": "negative", "annotations": [], "classes": []})
    assert save.status_code == 200, save.text
    stale = _snapshot(client, dataset_url, "quality")
    assert stale["status"] == "queued" and stale["stale"]
    assert stale["report"] == quality["report"] and stale["generated_at"] == quality["generated_at"]
    assert _snapshot(client, dataset_url, "validate")["stale"]
    assert _snapshot(client, dataset_url, "duplicates") == duplicates
    assert _ready(client, dataset_url, "quality")["report"]["items"][2]["value"] == 1

    _ready(client, dataset_url, "validate")
    split = client.patch(dataset_url + "/splits", json={"splits": {copy["id"]: "train"}})
    assert split.status_code == 200, split.text
    assert _snapshot(client, dataset_url, "quality")["status"] == "ready"
    assert not any(issue["code"] == "duplicate_across_splits"
                   for issue in _ready(client, dataset_url, "validate")["report"]["issues"])

    assert _refresh(client, dataset_url, "duplicates", force=True)["stale"]
    assert _snapshot(client, dataset_url, "validate")["stale"]


def test_interrupted_claim_is_recovered_and_superseded_output_is_rejected(client, dataset_url):
    dataset_id = dataset_url.rsplit("/", 1)[-1]
    _refresh(client, dataset_url, "quality")
    first = worker._claim()
    assert first is not None and first.dataset_id == dataset_id
    assert _snapshot(client, dataset_url, "quality")["status"] == "running"
    with Session(engine()) as db, db.begin():
        job = db.get(DatasetAnalysisJob, (dataset_id, "quality"))
        job.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    recovered = worker._claim()
    assert recovered is not None and recovered.token != first.token and recovered.revision == first.revision
    worker._publish(first, {"title": "old claim"})
    assert _snapshot(client, dataset_url, "quality")["report"] is None
    worker._publish(recovered, {"title": "recovered claim"})
    assert _snapshot(client, dataset_url, "quality")["report"]["title"] == "recovered claim"

    _refresh(client, dataset_url, "quality", force=True)
    current = worker._claim()
    assert current is not None
    upload = client.post(dataset_url + "/images", files={"files": ("new.png", _png(), "image/png")})
    assert upload.status_code == 200, upload.text
    worker._publish(current, {"title": "outdated generation"})
    state = _snapshot(client, dataset_url, "quality")
    assert state["stale"] and state["report"]["title"] == "recovered claim"
    assert _ready(client, dataset_url, "quality")["report"]["items"][3]["value"] == 1
