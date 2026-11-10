from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from stat import S_ISREG
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.database import engine
from app.core.storage import MAX_IMAGE_BYTES, open_checked_image, resolve_image
from app.dataset.models import DatasetImage
from app.quality.models import DatasetImageAnalysis


@dataclass(frozen=True)
class ImageFacts:
    exact: str | None = None
    dimensions: tuple[int, int] | None = None
    error: str | None = None


class ImageSource(Protocol):
    id: str
    storage_path: str


@dataclass(frozen=True)
class _Inspection:
    facts: ImageFacts
    signature: tuple[int, ...] | None = None
    checked_at: datetime | None = None


_RULE_VERSION = 1
_BATCH_SIZE = 256
_MISSING = "图片文件缺失"
_workers = ThreadPoolExecutor(max_workers=4, thread_name_prefix="image-check")


@lru_cache(maxsize=32_768)
def _read_facts(path: Path, signature: tuple[int, ...]) -> ImageFacts:
    with path.open("rb") as stream:
        data = stream.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            return ImageFacts(error="图片文件必须小于或等于 32 MiB")
    exact = sha256(data).hexdigest()
    try:
        with open_checked_image(data) as image:
            width, height = image.size
            if image.getexif().get(274, 1) in (5, 6, 7, 8):
                width, height = height, width
            return ImageFacts(exact, (width, height))
    except ValueError as exc:
        return ImageFacts(exact=exact, error=str(exc))


def _file_signature(path: Path) -> tuple[int, ...]:
    info = path.stat()
    if not S_ISREG(info.st_mode):
        raise FileNotFoundError(path)
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def signature_matches(storage_path: str, record: DatasetImageAnalysis) -> bool:
    if record.rule_version != _RULE_VERSION or not record.file_signature:
        return False
    try:
        return _file_signature(resolve_image(storage_path)) == tuple(record.file_signature)
    except (OSError, ValueError):
        return False


def _stored_facts(record: DatasetImageAnalysis) -> ImageFacts:
    dimensions = (record.width, record.height) if record.width is not None and record.height is not None else None
    return ImageFacts(record.sha256, dimensions, record.error)


def _inspect_file(storage_path: str, cached: DatasetImageAnalysis | None = None, *, persist: bool = False) -> _Inspection:
    try:
        path = resolve_image(storage_path)
        signature = _file_signature(path)
        if cached is not None and cached.file_signature is not None and tuple(cached.file_signature) == signature:
            return _Inspection(_stored_facts(cached))
        facts = _read_facts(path, signature)
        if not persist:
            return _Inspection(facts)
        if _file_signature(path) != signature:
            return _Inspection(ImageFacts(error="图片在检查过程中发生变化，请重新扫描"))
        return _Inspection(facts, signature, datetime.now(timezone.utc))
    except FileNotFoundError:
        write_missing = persist and (cached is None or cached.file_signature is not None or cached.error != _MISSING)
        return _Inspection(ImageFacts(error=_MISSING), checked_at=datetime.now(timezone.utc) if write_missing else None)
    except (OSError, ValueError) as exc:
        return _Inspection(ImageFacts(error=str(exc)))


def inspect_files(paths: Iterable[str]) -> Iterator[ImageFacts]:
    return (result.facts for result in _workers.map(_inspect_file, paths))


def _read_dataset_facts(dataset_id: str) -> dict[str, DatasetImageAnalysis]:
    with Session(engine()) as db:
        query = select(DatasetImageAnalysis).join(DatasetImage, DatasetImage.id == DatasetImageAnalysis.image_id)
        query = query.where(DatasetImage.dataset_id == dataset_id, DatasetImageAnalysis.rule_version == _RULE_VERSION)
        return {item.image_id: item for item in db.scalars(query)}


def _write_dataset_facts(dataset_id: str, changes: list[tuple[ImageSource, _Inspection]]) -> None:
    if not changes:
        return
    with Session(engine()) as db, db.begin():
        # Hold a brief key-share lock so a concurrent delete cannot break the foreign key during upsert.
        live_paths = dict(db.execute(select(DatasetImage.id, DatasetImage.storage_path).where(
            DatasetImage.dataset_id == dataset_id, DatasetImage.id.in_([image.id for image, _ in changes]),
        ).with_for_update(read=True, key_share=True)).tuples().all())
        rows = []
        for image, result in changes:
            if live_paths.get(image.id) != image.storage_path:
                continue
            facts = result.facts
            width, height = facts.dimensions or (None, None)
            rows.append(dict(image_id=image.id, file_signature=list(result.signature) if result.signature else None,
                             rule_version=_RULE_VERSION, sha256=facts.exact,
                             width=width, height=height, error=facts.error, checked_at=result.checked_at))
        if rows:
            statement = insert(DatasetImageAnalysis).values(rows)
            db.execute(statement.on_conflict_do_update(
                index_elements=[DatasetImageAnalysis.image_id],
                set_={column.name: statement.excluded[column.name] for column in DatasetImageAnalysis.__table__.columns
                      if column.name != "image_id"},
                where=statement.excluded.checked_at >= DatasetImageAnalysis.checked_at,
            ))


def inspect_dataset_files(
    dataset_id: str, images: Sequence[ImageSource], progress: Callable[[int, int], None],
) -> list[ImageFacts]:
    total = len(images)
    progress(0, total)
    cached = _read_dataset_facts(dataset_id)
    facts = []
    for start in range(0, total, _BATCH_SIZE):
        batch = images[start:start + _BATCH_SIZE]
        results = _workers.map(lambda image: _inspect_file(image.storage_path, cached.get(image.id), persist=True), batch)
        changes = []
        for image, result in zip(batch, results):
            facts.append(result.facts)
            if result.checked_at is not None:
                changes.append((image, result))
            progress(len(facts), total)
        _write_dataset_facts(dataset_id, changes)
    return facts
