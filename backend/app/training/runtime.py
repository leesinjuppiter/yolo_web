"""Public subset of the information recorded by the training worker."""

from math import isfinite


_ARGUMENTS = {
    "epochs", "batch", "imgsz", "device", "optimizer", "lr0", "lrf", "momentum", "weight_decay",
    "warmup_epochs", "seed", "patience", "amp", "workers", "deterministic", "cos_lr",
    "box", "cls", "dfl", "mosaic", "mixup", "degrees", "hsv_s", "close_mosaic",
}
_VERSIONS = {"torch", "torchvision", "ultralytics"}


def public_runtime(environment: dict | None) -> dict:
    env = environment or {}
    runtime = {}
    versions = {key: value for key, value in (env.get("versions") or {}).items()
                if key in _VERSIONS and isinstance(value, str)}
    if isinstance(env.get("python"), str) and (python := env["python"].split()):
        versions["python"] = python[0]
    if versions:
        runtime["versions"] = versions
    if type(env.get("processId")) is int and env["processId"] > 0:
        runtime["processId"] = env["processId"]
    arguments = env.get("arguments") or {}
    # The invocation stores planned arguments first. The runner later emits trainer.args, including task.
    if "task" in arguments:
        runtime["arguments"] = {
            key: value for key, value in arguments.items()
            if key in _ARGUMENTS and (
                isinstance(value, (str, bool, int)) or isinstance(value, float) and isfinite(value)
            )
        }
    return runtime
