"""Low-frequency measurements owned by the training worker."""

from datetime import datetime, timezone
import csv
import os
import subprocess
from time import monotonic

import psutil

from app.training.models import TrainingTask
from app.training.devices import normalize_gpu_uuid
from app.training.schemas import TERMINAL


_SAMPLE_INTERVAL = 2.0
_STALE_AFTER = 10.0


def _nvidia_query(arguments: list[str]) -> list[list[str]]:
    try:
        result = subprocess.run(
            ["nvidia-smi", *arguments, "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return list(csv.reader(result.stdout.splitlines(), skipinitialspace=True)) if result.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired):
        return []


def gpu_sample(device: dict, process_id: int) -> dict | None:
    uuid = normalize_gpu_uuid(device.get("uuid"))
    if device.get("kind") != "cuda" or not uuid:
        return None
    rows = _nvidia_query([f"--id={uuid}", "--query-gpu=uuid,utilization.gpu,memory.used,memory.total"])
    if not rows:
        return None
    row = rows[0]
    sample = {"deviceId": device["id"], "name": device["name"], "uuid": uuid}
    for position, key, multiplier in ((1, "utilizationPercent", 1), (2, "memoryUsedBytes", 1024**2),
                                      (3, "memoryTotalBytes", 1024**2)):
        try:
            sample[key] = float(row[position]) * multiplier
        except (ValueError, IndexError):
            pass
    processes = _nvidia_query(["--query-compute-apps=pid,gpu_uuid,used_gpu_memory"])
    for process in processes:
        try:
            if int(process[0]) == process_id and normalize_gpu_uuid(process[1]) == uuid:
                sample["processMemoryBytes"] = float(process[2]) * 1024**2
        except (ValueError, IndexError):
            continue
    return sample


class ResourceSampler:
    def __init__(self, process_id: int, *, device: dict | None = None) -> None:
        self._device = device or {}
        self._process_id = process_id
        self._process = None
        self._logical_cpus = psutil.cpu_count() or 1
        self._last_sample = monotonic()
        self._host_cpu_ready = False
        try:
            psutil.cpu_percent()
            self._host_cpu_ready = True
        except (OSError, psutil.Error):
            pass
        try:
            process = psutil.Process(process_id)
            process.cpu_percent()
            self._process = process
        except (OSError, psutil.Error):
            pass

    def sample(self) -> dict | None:
        now = monotonic()
        if now - self._last_sample < _SAMPLE_INTERVAL:
            return None
        self._last_sample = now
        values = {}
        try:
            host_cpu = psutil.cpu_percent()
            if self._host_cpu_ready:
                values["hostCpuPercent"] = host_cpu
            self._host_cpu_ready = True
            memory = psutil.virtual_memory()
            values.update(hostMemoryUsedBytes=memory.total - memory.available, hostMemoryTotalBytes=memory.total)
        except (OSError, psutil.Error):
            pass
        if self._process is not None:
            try:
                if self._process.is_running():
                    process_cpu = self._process.cpu_percent() / self._logical_cpus
                    process_memory = self._process.memory_info().rss
                    values.update(processId=self._process.pid, processCpuPercent=round(min(100, process_cpu), 2),
                                  processMemoryBytes=process_memory)
            except (OSError, psutil.Error):
                pass
        if gpu := gpu_sample(self._device, self._process_id):
            values["gpu"] = gpu
        return {"sampledAt": datetime.now(timezone.utc).isoformat(), **values} if values else None


def resource_status(task: TrainingTask) -> dict:
    environment = task.environment or {}
    sample = environment.get("resourceSample")
    if task.status in TERMINAL:
        state = "finished"
    elif sample:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(sample["sampledAt"])).total_seconds()
        state = "stale" if task.phase == "archiving" or age > _STALE_AFTER else "live"
    elif task.status in ("created", "queued") or not environment.get("processId"):
        state = "waiting"
    else:
        state = "unavailable"
    return {"state": state, **({"sample": sample} if sample else {})}
