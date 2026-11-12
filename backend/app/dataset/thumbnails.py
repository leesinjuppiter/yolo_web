from pathlib import Path
from uuid import uuid4

from PIL import Image

from app.core.config import data_dir


def thumbnail_path(source: Path, *, cache_key: str | None = None) -> Path:
    """Images have immutable storage IDs; generate the small derivative once."""
    target = data_dir() / "thumbnails" / f"{cache_key or source.stem}.jpg"
    if target.is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f".{uuid4().hex}.tmp")
    try:
        with Image.open(source) as image:
            image.thumbnail((160, 160), Image.Resampling.LANCZOS)
            image.convert("RGB").save(temporary, format="JPEG", quality=75, optimize=True)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target
