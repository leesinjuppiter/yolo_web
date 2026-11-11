"""Verify a package directory without importing third party dependencies."""

import hashlib
from pathlib import Path


def verify(root: Path) -> int:
    root = root.resolve()
    expected = set()
    for line in (root/"checksum.sha256").read_text(encoding="utf-8").splitlines():
        value, relative = line.split("  ", 1)
        path = root/relative
        if path.is_symlink() or not path.resolve().is_relative_to(root) or relative in expected:
            raise ValueError("Unsafe or duplicate checksum member")
        expected.add(relative)
        with path.open("rb") as source:
            actual = hashlib.file_digest(source, "sha256").hexdigest()
        if actual != value:
            raise ValueError(f"Checksum mismatch: {relative}")
    actual_files = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    if actual_files != expected | {"checksum.sha256"}:
        raise ValueError("Package member list differs from checksum manifest")
    return len(expected)


if __name__ == "__main__":
    print(f"Verified {verify(Path(__file__).resolve().parents[1])} files")
