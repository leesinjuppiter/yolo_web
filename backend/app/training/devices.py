"""Worker-owned device capabilities; the API never probes its own CUDA context."""

import json
import os
import re
import sys
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from time import monotonic

from app.core.config import data_dir
from app.training.cpu import CPU, cpu_device

_last_publish = -float("inf")
_cached_probe: dict | None = None
_STALE_SECONDS = 20


class DeviceUnavailableError(ValueError):
    pass


def normalize_gpu_uuid(value: object) -> str:
    uuid = str(value or "")
    if re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", uuid):
        return f"GPU-{uuid}"
    return uuid


def probe_devices() -> dict:
    result = {"devices": [cpu_device()], "versions": {"python": sys.version.split()[0]}}
    try:
        import torch

        result["versions"].update(torch=torch.__version__, cuda=torch.version.cuda)
        if not torch.cuda.is_available():
            result["reason"] = "执行环境未提供可用 CUDA GPU，CPU 任务仍可运行"
        else:
            for index in range(torch.cuda.device_count()):
                info = torch.cuda.get_device_properties(index)
                result["devices"].append({
                    "id": f"cuda:{index}", "name": info.name, "kind": "cuda", "logicalIndex": index,
                    "memoryBytes": info.total_memory, "uuid": normalize_gpu_uuid(getattr(info, "uuid", "")),
                })
        result["versions"]["ultralytics"] = version("ultralytics")
    except (ImportError, RuntimeError, OSError, PackageNotFoundError) as exc:
        result["reason"] = f"训练执行环境检测失败：{type(exc).__name__}"
    result["cudaVisibleDevices"] = os.environ.get("CUDA_VISIBLE_DEVICES")
    return result


def _capability_path() -> Path:
    return data_dir() / "training" / "worker-capabilities.json"


def publish_capabilities(*, force: bool = False) -> None:
    global _last_publish, _cached_probe
    now = monotonic()
    if not force and now - _last_publish < 5:
        return
    if force or _cached_probe is None:
        _cached_probe = probe_devices()
    path = _capability_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**_cached_probe, "sampledAt": datetime.now(timezone.utc).isoformat(), "processId": os.getpid()}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    _last_publish = now


def capabilities() -> dict:
    try:
        payload = json.loads(_capability_path().read_text(encoding="utf-8"))
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(payload["sampledAt"])).total_seconds()
        if age < 0 or age > _STALE_SECONDS:
            return {"devices": [CPU], "workerStatus": {"state": "stale", "reason": "训练执行器心跳已过期"}}
        return {"devices": payload["devices"], "workerStatus": {
            "state": "live", "sampledAt": payload["sampledAt"], "versions": payload.get("versions", {}),
            **({"reason": payload["reason"]} if payload.get("reason") else {}),
        }}
    except (OSError, ValueError, KeyError, TypeError):
        return {"devices": [CPU], "workerStatus": {"state": "unavailable", "reason": "训练执行器尚未发布设备能力"}}


def available_devices() -> list[dict]:
    return capabilities()["devices"]


def validate_device(device_id: str, *, execution: bool = False) -> dict:
    devices = probe_devices()["devices"] if execution else available_devices()
    device = next((item for item in devices if item["id"] == device_id), None)
    if device is None:
        raise DeviceUnavailableError("所选训练设备不可用，请检查执行器状态和 CUDA 环境；不会自动切换到 CPU")
    return device


def device_description(device_id: str) -> dict:
    return next((item for item in available_devices() if item["id"] == device_id),
                {"id": device_id, "name": device_id, "kind": "cpu" if device_id == "cpu" else "cuda"})
