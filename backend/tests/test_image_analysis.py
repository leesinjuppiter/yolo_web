import os

from sqlalchemy.orm import Session

from app.core.database import engine
from app.core.storage import resolve_image
from app.dataset.models import DatasetImage
from app.quality import fingerprints
from app.quality.fingerprints import ImageFacts, inspect_dataset_files
from app.quality.models import DatasetImageAnalysis
from app.quality.report import duplicate_report
from test_dataset_api import _png, client, dataset_url


def _upload_image(client, dataset_url):
    response = client.post(dataset_url + "/images", files={"files": ("sample.png", _png(), "image/png")})
    assert response.status_code == 200, response.text
    image_id = response.json()["images"][0]["id"]
    with Session(engine()) as db:
        return db.get(DatasetImage, image_id)


def _saved_facts(image_id):
    with Session(engine()) as db:
        return db.get(DatasetImageAnalysis, image_id)


def test_image_analysis_reuses_persisted_facts_and_rechecks_changed_files(client, dataset_url, monkeypatch):
    image = _upload_image(client, dataset_url)
    path = resolve_image(image.storage_path)
    original = path.read_bytes()
    decode = fingerprints.open_checked_image
    decoded = []
    updates = []

    def count_decode(data):
        decoded.append(len(data))
        return decode(data)

    def scan():
        return inspect_dataset_files(image.dataset_id, [image], lambda completed, total: updates.append((completed, total)))[0]

    monkeypatch.setattr(fingerprints, "open_checked_image", count_decode)
    initial = scan()
    record = _saved_facts(image.id)
    assert initial.exact == record.sha256 and initial.dimensions == (record.width, record.height)
    assert record.dhash is None
    assert updates == [(0, 1), (1, 1)]

    fingerprints._read_facts.cache_clear()
    assert scan() == initial
    assert len(decoded) == 1
    assert _saved_facts(image.id).checked_at == record.checked_at

    info = path.stat()
    path.write_bytes(b"x" * len(original))
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
    changed = scan()
    assert changed.error and changed.exact != initial.exact
    assert _saved_facts(image.id).error == changed.error

    path.unlink()
    assert scan() == ImageFacts(error="图片文件缺失")
    assert _saved_facts(image.id).file_signature is None
    path.write_bytes(original)
    assert scan() == initial


def test_image_analysis_skips_persist_when_image_is_deleted_during_scan(client, dataset_url):
    image = _upload_image(client, dataset_url)

    def delete_before_upsert(completed, total):
        if completed == total:
            response = client.delete(f"{dataset_url}/images/{image.id}")
            assert response.status_code == 204, response.text

    assert inspect_dataset_files(image.dataset_id, [image], delete_before_upsert)[0].exact
    assert _saved_facts(image.id) is None


def test_duplicate_snapshot_keeps_both_image_ids():
    images = [(name, f"images/{name}") for name in ("first", "copy", "similar", "broken")]
    facts = [ImageFacts("a"), ImageFacts("a"), ImageFacts("b"), ImageFacts(error="损坏")]
    report = duplicate_report(images, facts, image_ids=("0", "1", "2", "3"))
    assert [item.value for item in report.items] == [1, 1, 1, 3]
    assert [(issue.code, issue.image_id, issue.related_image_id) for issue in report.issues] == [
        ("duplicate_exact", "1", "0"), ("image_invalid", "3", None),
    ]
