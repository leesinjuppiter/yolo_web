"""Read a portable YOLO archive without extracting member paths."""

from collections.abc import Callable, Collection, Iterable
from pathlib import PurePosixPath
from stat import S_IFLNK, S_IFMT
from zipfile import ZipFile, ZipInfo

import yaml

MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_EXPANDED_BYTES = 1024 * 1024 * 1024
MAX_MEMBERS = 30_000
MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_TEXT_BYTES = 2 * 1024 * 1024
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
SPLITS = ("train", "val", "test")


def _safe_path(name: str) -> PurePosixPath:
    if "\\" in name or ":" in name or any(ord(char) < 32 for char in name):
        raise ValueError("ZIP 包含不安全的文件路径")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("ZIP 包含不安全的文件路径")
    return path


def inspect_members(archive: ZipFile) -> dict[PurePosixPath, ZipInfo]:
    entries = archive.infolist()
    if len(entries) > MAX_MEMBERS or sum(item.file_size for item in entries) > MAX_EXPANDED_BYTES:
        raise ValueError("ZIP 解压大小或文件数量超过限制")
    files = {}
    keys = set()
    for item in entries:
        path = _safe_path(item.orig_filename)
        if S_IFMT(item.external_attr >> 16) == S_IFLNK or item.flag_bits & 1:
            raise ValueError("ZIP 不支持符号链接或加密文件")
        if not item.is_dir():
            key = str(path).casefold()
            if key in keys:
                raise ValueError("ZIP 包含冲突的文件名")
            keys.add(key)
            files[path] = item
    return files


def read_bytes(archive: ZipFile, entry: ZipInfo, limit: int) -> bytes:
    if entry.file_size > limit:
        raise ValueError(f"ZIP 文件超过单项大小限制：{entry.filename}")
    with archive.open(entry) as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"ZIP 文件超过单项大小限制：{entry.filename}")
    return data


def read_config(files: Collection[PurePosixPath], text_at: Callable[[PurePosixPath], str],
                required: bool) -> tuple[PurePosixPath, dict]:
    candidates = [path for path in files if path.name.lower() in ("data.yaml", "dataset.yaml", "data.yml", "dataset.yml")]
    if not candidates and not required:
        return PurePosixPath("."), {}
    if len(candidates) != 1:
        raise ValueError("数据集须包含唯一的 data.yaml 或 dataset.yaml")
    path = candidates[0]
    try:
        config = yaml.safe_load(text_at(path))
    except yaml.YAMLError as exc:
        raise ValueError("无法解析 YOLO 数据集配置") from exc
    if not isinstance(config, dict):
        raise ValueError("YOLO 数据集配置须为键值映射")
    # The archive is its own root. An authoring-machine path is not resolved.
    return path.parent, config


def _classes(value: object) -> list[str]:
    if isinstance(value, dict):
        indexed = {}
        for key, name in value.items():
            if type(key) is not int and not (isinstance(key, str) and key.isdecimal()):
                raise ValueError("类别编号须为从 0 开始的连续整数")
            index = int(key)
            if index in indexed:
                raise ValueError("类别编号重复")
            indexed[index] = name
        if set(indexed) != set(range(len(indexed))):
            raise ValueError("类别编号须为从 0 开始的连续整数")
        value = [indexed[index] for index in range(len(indexed))]
    if not isinstance(value, list) or not value or any(not isinstance(name, str) or not name.strip() for name in value):
        raise ValueError("配置须定义有效的 names 类别列表")
    names = [name.strip() for name in value]
    if len(names) != len(set(names)):
        raise ValueError("配置中的类别名称重复")
    return names


def pose_schema(config: dict, class_count: int) -> tuple[list[str], int]:
    shape = config.get("kpt_shape")
    if (not isinstance(shape, list) or len(shape) != 2 or type(shape[0]) is not int
            or not 1 <= shape[0] <= 100 or type(shape[1]) is not int or shape[1] not in (2, 3)):
        raise ValueError("姿态数据须提供 kpt_shape: [关键点数量, 2 或 3]")
    names = config.get("kpt_names")
    if isinstance(names, dict):
        schemas = [names.get(index, names.get(str(index))) for index in range(class_count)]
        if not schemas or not isinstance(schemas[0], list) or any(row != schemas[0] for row in schemas):
            raise ValueError("所有类别须使用同一套关键点名称和顺序")
        names = schemas[0]
    if names is None:
        names = [f"kpt_{index + 1}" for index in range(shape[0])]
    if not isinstance(names, list) or len(names) != shape[0] or _classes(names) != names:
        raise ValueError("关键点名称须与 kpt_shape 匹配")
    return names, shape[1]


def _under(path: PurePosixPath, directory: PurePosixPath) -> bool:
    return path != directory and path.is_relative_to(directory)


def archive_reference(base: PurePosixPath, value: str) -> PurePosixPath:
    return base / _safe_path(value)


def _image_paths(files: Collection[PurePosixPath], root: PurePosixPath, source: str,
                 image_paths: list[PurePosixPath], text_at: Callable[[PurePosixPath], str],
                 reference: Callable[[PurePosixPath, str], PurePosixPath]) -> Iterable[PurePosixPath]:
    path = reference(root, source)
    if path.suffix.lower() == ".txt":
        if path not in files:
            raise ValueError(f"分集清单缺失：{path}")
        for line in text_at(path).splitlines():
            if not line.strip():
                continue
            image = reference(path.parent, line.strip())
            if image not in files:
                image = reference(root, line.strip())
            if image not in files or image.suffix.lower() not in IMAGE_EXTENSIONS:
                raise ValueError(f"分集清单引用了数据集中不存在的图片：{line.strip()}")
            yield image
    else:
        yield from (image for image in image_paths if _under(image, path))


def detection_index(files: Collection[PurePosixPath], root: PurePosixPath, config: dict,
                    text_at: Callable[[PurePosixPath], str],
                    reference: Callable[[PurePosixPath, str], PurePosixPath]) -> tuple[list[str], list[tuple[PurePosixPath, str, str | None]]]:
    image_paths = [path for path in files if path.suffix.lower() in IMAGE_EXTENSIONS]
    entries: dict[PurePosixPath, tuple[str, str | None]] = {}
    for split in SPLITS:
        sources = config.get(split) or [f"images/{split}", f"{split}/images"]
        if isinstance(sources, str):
            sources = [sources]
        if not isinstance(sources, list) or any(not isinstance(source, str) for source in sources):
            raise ValueError(f"{split} 分集须引用数据集内的图片目录或清单")
        for source in sources:
            for path in _image_paths(files, root, source, image_paths, text_at, reference):
                if path in entries and entries[path][0] != split:
                    raise ValueError(f"图片同时出现在多个分集：{path}")
                entries[path] = (split, None)
    return _classes(config.get("names")), [(path, *entry) for path, entry in entries.items()]


def classification_index(files: Collection[PurePosixPath]) -> tuple[list[str], list[tuple[PurePosixPath, str, str | None]]]:
    entries = []
    roots = set()
    for path in files:
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        for index, part in enumerate(path.parts[:-2]):
            if part in SPLITS or part == "valid":
                roots.add(path.parts[:index])
                entries.append((path, "val" if part == "valid" else part, path.parts[index + 1]))
                break
    if len(roots) > 1:
        raise ValueError("分类数据须使用同一个根目录下的 train、val 或 test 目录")
    names = sorted({name for _, _, name in entries}, key=str.casefold)
    return names, entries


def label_path(image: PurePosixPath) -> PurePosixPath:
    parts = list(image.parts)
    try:
        index = len(parts) - 1 - parts[::-1].index("images")
    except ValueError:
        return image.with_suffix(".txt")
    parts[index] = "labels"
    return PurePosixPath(*parts).with_suffix(".txt")
