"""Read-only image access against the completed evaluation's frozen input."""
import json
from hashlib import sha256
from pathlib import Path

from app.dataset.repository import NotFound
from app.dataset.thumbnails import thumbnail_path
from app.evaluation.snapshot import _read_checked


def frozen_image(directory: Path, snapshot_digest: str, image_id: str, thumbnail=False) -> Path:
    root = directory / "input"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    actual = sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if actual != snapshot_digest:
        raise ValueError("评估快照清单校验失败")
    sample = next((row for row in manifest["samples"]
                   if str(row.get("image_id", Path(row["image_path"]).stem)) == image_id), None)
    if sample is None:
        raise NotFound("评估图片不存在")
    _read_checked(root, sample["image_path"], sample["image_sha256"])
    path = (root / sample["image_path"]).resolve()
    return thumbnail_path(path, cache_key=sample["image_sha256"]) if thumbnail else path
