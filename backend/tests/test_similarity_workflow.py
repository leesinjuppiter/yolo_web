from io import BytesIO
from uuid import uuid4

from PIL import Image
from PIL.PngImagePlugin import PngInfo
from sqlalchemy.orm import Session

from app.core.database import engine
from app.core.storage import resolve_image
from app.dataset.models import DatasetImage
from app.quality.models import DatasetImageAnalysis
from test_dataset_api import client, dataset_url
from test_report_snapshots import _ready, _snapshot


def _upload_copies(client, dataset_url, names, *, different_file=None):
    for name in names:
        output = BytesIO()
        info = PngInfo()
        info.add_text("sample", name if name == different_file else "copy")
        Image.new("RGB", (100, 80), "#39516a").save(output, "PNG", pnginfo=info)
        response = client.post(dataset_url + "/images", files={"files": (name, output.getvalue(), "image/png")})
        assert response.status_code == 200, response.text
    return {image["name"]: image for image in response.json()["images"]}


def _pair(report, first, second, status="pending"):
    return next(issue for issue in report["issues"] if issue["review_status"] == status
                and {issue["image_id"], issue["related_image_id"]} == {first["id"], second["id"]})


def _submit(client, dataset_url, issue, decision, expected=204):
    keys = ("image_id", "related_image_id", "image_sha256", "related_image_sha256")
    response = client.post(dataset_url + "/similarity-reviews", json={
        **{key: issue[key] for key in keys}, "decision": decision,
    })
    assert response.status_code == expected, response.text


def test_duplicate_review_keeps_confirmed_pair_and_restores_excluded_annotation(client, dataset_url):
    images = _upload_copies(client, dataset_url, ["a.png", "b.png", "c.png"])
    a, b, c = (images[f"{name}.png"] for name in "abc")
    category = {"id": str(uuid4()), "name": "coal", "color": "#135791"}
    annotation = {"id": str(uuid4()), "type": "obb", "class_id": category["id"], "source": "manual",
                  "obb": {"cx": 50, "cy": 40, "width": 20, "height": 10, "angle": 15}}
    save_url = f"{dataset_url}/images/{b['id']}/annotations?compact=true"
    payload = {"version": 0, "status": "annotated", "annotations": [annotation], "classes": [category]}
    saved = client.put(save_url, json=payload)
    assert saved.status_code == 200, saved.text

    report = _ready(client, dataset_url, "duplicates")["report"]
    retained = _pair(report, a, c)
    _submit(client, dataset_url, retained, "keep_both")
    assert _snapshot(client, dataset_url, "duplicates")["stale"]
    _submit(client, dataset_url, retained, "keep_both", expected=409)
    report = _ready(client, dataset_url, "duplicates")["report"]
    assert _pair(report, a, c, "confirmed")

    discard = _pair(report, a, b)
    _submit(client, dataset_url, discard, "discard_image" if discard["image_id"] == b["id"] else "discard_related")
    assert {image["id"] for image in client.get(dataset_url).json()["images"]} == {a["id"], c["id"]}
    excluded, = client.get(dataset_url + "/excluded-images").json()
    assert excluded["id"] == b["id"] and excluded["excluded_at"]
    assert excluded["annotations"] == saved.json()["image"]["annotations"]
    assert client.get(b["url"]).status_code == 200
    assert client.put(save_url, json=payload).status_code == 404
    assert _ready(client, dataset_url, "quality")["report"]["items"][-1]["value"] == 0
    report = _ready(client, dataset_url, "duplicates")["report"]
    assert [item["review_status"] for item in report["issues"]] == ["confirmed"]

    restored = client.post(f"{dataset_url}/excluded-images/{b['id']}/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["annotations"] == excluded["annotations"]
    assert restored.json()["excluded_at"] is None and restored.json()["version"] > saved.json()["image"]["version"]
    assert client.get(dataset_url + "/excluded-images").json() == []
    assert _ready(client, dataset_url, "quality")["report"]["items"][-1]["value"] == 1


def test_review_rejects_original_changed_after_snapshot(client, dataset_url):
    images = _upload_copies(client, dataset_url, ["a.png", "b.png"])
    report = _ready(client, dataset_url, "duplicates")["report"]
    issue = _pair(report, images["a.png"], images["b.png"])
    with Session(engine()) as db:
        path = resolve_image(db.get(DatasetImage, issue["image_id"]).storage_path)
    path.write_bytes(b"changed externally")
    _submit(client, dataset_url, issue, "discard_image", expected=409)
    assert len(client.get(dataset_url).json()["images"]) == 2
    assert client.get(dataset_url + "/excluded-images").json() == []


def test_review_accepts_other_valid_pairs_while_report_is_queued(client, dataset_url):
    images = _upload_copies(client, dataset_url, [f"{name}.png" for name in "abcde"])
    a, b, c, d, e = (images[f"{name}.png"] for name in "abcde")
    report = _ready(client, dataset_url, "duplicates")["report"]

    _submit(client, dataset_url, _pair(report, a, b), "keep_both")
    assert _snapshot(client, dataset_url, "duplicates")["status"] == "queued"
    _submit(client, dataset_url, _pair(report, a, c), "keep_both")
    discarded = _pair(report, a, d)
    _submit(client, dataset_url, discarded, "discard_image" if discarded["image_id"] == d["id"] else "discard_related")
    _submit(client, dataset_url, _pair(report, a, e), "keep_both")

    _submit(client, dataset_url, _pair(report, a, b), "keep_both", expected=409)
    _submit(client, dataset_url, discarded, "keep_both", expected=409)
    assert [image["id"] for image in client.get(dataset_url + "/excluded-images").json()] == [d["id"]]
    refreshed = _ready(client, dataset_url, "duplicates")["report"]
    assert _pair(refreshed, a, c, "confirmed") and _pair(refreshed, a, e, "confirmed")


def test_same_pixels_with_different_file_bytes_are_not_reviewable(client, dataset_url):
    images = _upload_copies(client, dataset_url, ["a.png", "b.png", "c.png"], different_file="c.png")
    a, b, c = (images[f"{name}.png"] for name in "abc")
    report = _ready(client, dataset_url, "duplicates")["report"]
    issue, = report["issues"]
    assert issue == _pair(report, a, b) and issue["code"] == "duplicate_exact"
    assert issue["image_sha256"] == issue["related_image_sha256"]
    _submit(client, dataset_url, issue, "not_similar", expected=422)
    with Session(engine()) as db:
        different_sha = db.get(DatasetImageAnalysis, c["id"]).sha256
    _submit(client, dataset_url, {**issue, "related_image_id": c["id"], "related_image_sha256": different_sha},
            "keep_both", expected=422)
