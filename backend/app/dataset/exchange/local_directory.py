"""Browse and read local dataset directories on the workbench machine."""

import os
from pathlib import Path, PurePosixPath
from stat import FILE_ATTRIBUTE_REPARSE_POINT
from string import ascii_uppercase

from .archive import IMAGE_EXTENSIONS


def _linked(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)


def directory_root(value: str) -> Path:
    raw = value.strip().strip('"')
    path = Path(raw)
    if not path.is_absolute() or raw.startswith(("//", "\\\\")):
        raise ValueError("请选择本机磁盘上的绝对目录")
    try:
        if _linked(path) or not path.is_dir():
            raise ValueError("请选择可读取的普通目录")
        root = path.resolve(strict=True)
        if str(root).startswith(("//", "\\\\")):
            raise ValueError("请选择本机磁盘上的绝对目录")
        return root
    except (OSError, RuntimeError) as exc:
        raise ValueError("无法读取该目录，请检查路径和访问权限") from exc


def list_local_directories(value: str | None) -> dict:
    if not value:
        if os.name == "nt":
            roots = [Path(f"{letter}:/") for letter in ascii_uppercase]
        else:
            roots = [Path.home(), Path("/")]
        return {"path": None, "parent": None, "directories": [
            {"name": str(path), "path": str(path)} for path in roots if path.is_dir()
        ]}
    root = directory_root(value)
    children = []
    try:
        for child in root.iterdir():
            if child.name.startswith("."):
                continue
            try:
                if not _linked(child) and child.is_dir():
                    children.append(child)
            except OSError:
                continue
    except OSError as exc:
        raise ValueError("无法列出该目录，请检查访问权限") from exc
    return {
        "path": str(root), "parent": str(root.parent) if root != root.parent else None,
        "directories": [{"name": child.name, "path": str(child)} for child in sorted(children, key=lambda child: child.name.casefold())],
    }


def directory_members(root: Path, *, extra_suffixes: frozenset[str] = frozenset()) -> set[PurePosixPath]:
    if root == root.parent:
        raise ValueError("请选择具体的 YOLO 数据集目录")
    members = set()
    suffixes = IMAGE_EXTENSIONS | {".yaml", ".yml", ".txt"} | extra_suffixes

    def fail(error: OSError) -> None:
        raise error

    try:
        for folder, dirs, files in os.walk(root, onerror=fail):
            current = Path(folder)
            dirs[:] = [name for name in dirs if not name.startswith(".") and not _linked(current / name)]
            for name in files:
                path = current / name
                if path.suffix.lower() in suffixes and not _linked(path) and path.is_file():
                    members.add(PurePosixPath(path.relative_to(root).as_posix()))
    except OSError as exc:
        raise ValueError("无法扫描数据集目录，请检查访问权限和文件是否仍在原位") from exc
    return members


def directory_reference(root: Path, base: PurePosixPath, value: str) -> PurePosixPath:
    if value.startswith(("//", "\\\\")):
        raise ValueError("数据集配置只能引用所选目录内的路径")
    source = Path(value)
    target = source if source.is_absolute() else root.joinpath(*base.parts, source)
    try:
        relative = target.resolve().relative_to(root)
    except (ValueError, OSError, RuntimeError) as exc:
        raise ValueError(f"分集路径超出所选目录：{value}") from exc
    return PurePosixPath(relative.as_posix())


def read_directory_file(root: Path, path: PurePosixPath, limit: int) -> bytes:
    target = root.joinpath(*path.parts)
    try:
        if _linked(target) or not target.resolve(strict=True).is_relative_to(root):
            raise ValueError(f"数据集文件超出所选目录：{path}")
        with target.open("rb") as stream:
            data = stream.read(limit + 1)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"无法读取数据集文件：{path}") from exc
    if len(data) > limit:
        raise ValueError(f"数据集文件超过单项大小限制：{path}")
    return data
