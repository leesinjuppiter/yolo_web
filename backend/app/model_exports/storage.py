import json
from hashlib import file_digest
from pathlib import Path
from uuid import UUID

from app.core.config import data_dir


def export_dir(task_id: str) -> Path:
    return data_dir() / "model_exports" / str(UUID(task_id))


def package_dir(task_id: str) -> Path:
    return data_dir() / "deployment_packages" / str(UUID(task_id))


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return file_digest(source, "sha256").hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
