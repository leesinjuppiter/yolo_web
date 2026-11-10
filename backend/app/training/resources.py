"""Low-frequency measurements owned by the training worker."""

from datetime import datetime, timezone
from time import monotonic

import psutil

from app.training.models import TrainingTask
from app.training.schemas import TERMINAL


_SAMPLE_INTERVAL = 2.0
_STALE_AFTER = 10.0


class ResourceSampler:
    def __init__(self, process_id: int) -> None:
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
