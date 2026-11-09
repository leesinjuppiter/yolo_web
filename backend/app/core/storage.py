import logging
from collections.abc import Iterable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import data_dir

MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
_IMAGE_SUFFIXES = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "BMP": ".bmp"}
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredImage:
    path: str
    width: int
    height: int


def _decode_image(data: bytes) -> tuple[int, int, str, bytes]:
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("图片文件必须小于或等于 32 MiB")
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format not in _IMAGE_SUFFIXES:
                raise ValueError("支持 JPEG、PNG、WebP 和 BMP 图片")
            width, height = image.size
            if width * height > MAX_IMAGE_PIXELS:
                raise ValueError("图片不能超过 4000 万像素")
            image_format = image.format
            suffix = _IMAGE_SUFFIXES[image_format]
            image.verify()
        with Image.open(BytesIO(data)) as image:
            image.load()
            if image.getexif().get(274, 1) in range(2, 9):
                width, height, data = _normalize_orientation(image, image_format)
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as error:
        raise ValueError("无法读取图片内容") from error
    return width, height, suffix, data


def _normalize_orientation(image: Image.Image, image_format: str) -> tuple[int, int, bytes]:
    options = {"quality": 95} if image_format == "JPEG" else {}
    if image_format == "WEBP":
        options["lossless"] = True
    if profile := image.info.get("icc_profile"):
        options["icc_profile"] = profile
    output = BytesIO()
    with ImageOps.exif_transpose(image) as oriented:
        oriented.save(output, format=image_format, **options)
        return oriented.width, oriented.height, output.getvalue()


def inspect_image(data: bytes) -> tuple[int, int, str]:
    width, height, suffix, _ = _decode_image(data)
    return width, height, suffix


def resolve_image(path: str) -> Path:
    root = data_dir() / "images"
    candidate = (data_dir() / path).resolve()
    if not candidate.is_relative_to(root) or candidate == root:
        raise ValueError("图片存储路径无效")
    return candidate


def save_image(data: bytes) -> StoredImage:
    width, height, suffix, data = _decode_image(data)
    path = "images/" + uuid4().hex + suffix
    destination = resolve_image(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".part")
    try:
        temporary.write_bytes(data)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return StoredImage(path, width, height)


def remove_images(paths: Iterable[str]) -> None:
    for path in paths:
        try:
            resolve_image(path).unlink(missing_ok=True)
        except (OSError, ValueError):
            log.exception("无法清理图片文件 %s", path)
