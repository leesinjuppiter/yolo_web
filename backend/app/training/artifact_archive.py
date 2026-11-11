from hashlib import sha256
from tempfile import TemporaryFile
from typing import BinaryIO
from zipfile import ZIP_DEFLATED, ZipFile

from app.dataset.repository import Conflict, NotFound
from app.training import repository
from app.training.models import TrainingTask
from app.training.schemas import TERMINAL


def build_archive(task: TrainingTask) -> BinaryIO:
    if task.status not in TERMINAL:
        raise Conflict("请等待训练结束后下载训练产物")
    if not task.artifacts:
        raise NotFound("任务尚未归档训练产物")
    output = TemporaryFile(mode="w+b")
    try:
        with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=1) as archive:
            for artifact in task.artifacts:
                item, path = repository.artifact_file(task, artifact["id"])
                relative = path.relative_to(repository.task_dir(task.id).resolve()).as_posix()
                digest, size = sha256(), 0
                with path.open("rb") as source, archive.open(relative, "w", force_zip64=True) as target:
                    while chunk := source.read(1024 * 1024):
                        target.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                if digest.hexdigest() != item["sha256"] or size != item["sizeBytes"]:
                    raise Conflict(f"训练产物校验失败：{item['name']}，请检查原始文件")
        output.seek(0)
        return output
    except BaseException:
        output.close()
        raise


def stream_archive(output: BinaryIO):
    try:
        while chunk := output.read(1024 * 1024):
            yield chunk
    finally:
        output.close()
