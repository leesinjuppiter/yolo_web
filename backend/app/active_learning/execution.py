"""Process and file IO owned by the recommendation executor."""
import json
import os
import subprocess
import sys
import shutil
from hashlib import file_digest

from app.active_learning.storage import directory


def start(task, iteration, model_path):
    root = directory(task.id)
    root.mkdir(parents=True, exist_ok=True)
    frozen_model = root / "model.pt"
    shutil.copyfile(model_path, frozen_model)
    with frozen_model.open("rb") as stream:
        actual = file_digest(stream, "sha256").hexdigest()
    if actual != iteration.source["modelSha256"]:
        raise ValueError("基线模型复制校验失败，权重已变化")
    job = {"config": task.config, "inputs": task.inputs, "taskType": iteration.task_type,
           "classes": iteration.source["classes"], "modelPath": str(frozen_model),
           "modelSha256": actual, "output": str(root / "result.json")}
    (root / "job.json").write_text(json.dumps(job), encoding="utf-8")
    output = (root / "stdout.log").open("wb")
    process = subprocess.Popen([sys.executable, "-B", "-u", "-m", "app.active_learning.runner", str(root / "job.json")],
        stdout=output, stderr=subprocess.STDOUT, env={**os.environ, "YOLO_AUTOINSTALL": "False"})
    output.close()
    return process


def read_progress(identifier):
    path = directory(identifier) / "stdout.log"
    if not path.exists():
        return 0
    with path.open("rb") as source:
        source.seek(max(0, path.stat().st_size - 8192))
        lines = source.read().decode("utf-8", errors="replace").splitlines()
    for line in reversed(lines):
        if line.startswith('{"processed":'):
            return json.loads(line)["processed"]
    return 0


def read_result(identifier):
    return json.loads((directory(identifier) / "result.json").read_text(encoding="utf-8"))
