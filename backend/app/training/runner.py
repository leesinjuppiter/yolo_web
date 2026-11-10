"""Isolated, offline Ultralytics subprocess. The worker owns the database."""

import json
import math
import os
import signal
import sys
import traceback
from importlib.metadata import version
from pathlib import Path
from threading import Thread, enumerate as threads
from time import monotonic


METRIC_NAMES = {
    "train/box_loss": "boxLoss", "train/cls_loss": "clsLoss", "train/dfl_loss": "dflLoss",
    "train/seg_loss": "segLoss", "train/loss": "clsLoss", "val/loss": "valLoss",
    "val/box_loss": "valBoxLoss", "val/cls_loss": "valClsLoss", "val/dfl_loss": "valDflLoss",
    "val/seg_loss": "valSegLoss", "metrics/precision(B)": "precision", "metrics/recall(B)": "recall",
    "metrics/mAP50(B)": "map50", "metrics/mAP50-95(B)": "map50_95",
    "metrics/mAP50(M)": "maskMap50", "metrics/mAP50-95(M)": "maskMap50_95",
    "metrics/accuracy_top1": "top1", "metrics/accuracy_top5": "top5", "lr/pg0": "learningRate",
}


def _values(raw: dict) -> dict[str, float]:
    values = {}
    for name, raw_value in raw.items():
        value = float(raw_value)
        if math.isfinite(value):
            values[name] = value
            values[METRIC_NAMES.get(name, name)] = value
    return values


def _callbacks(model, emit):
    start = monotonic()
    step = 0
    last_epoch = 0

    def setup(trainer):
        emit("environment", arguments=vars(trainer.args))
        emit("phase", phase="training")

    def batch(_trainer):
        nonlocal step
        step += 1

    def epoch(trainer):
        nonlocal last_epoch
        current = int(trainer.epoch) + 1
        # The standalone best-checkpoint validation uses a synthetic next epoch.
        if current <= last_epoch or not trainer.validator.training:
            return
        last_epoch = current
        emit("metric", epoch=current, step=step, elapsedSeconds=monotonic() - start,
             values=_values({**trainer.label_loss_items(trainer.tloss), **trainer.metrics, **trainer.lr}))

    def validation(validator):
        if not validator.training:
            emit("phase", phase="validation")
            validator.args.plots = True

    model.add_callback("on_train_start", setup)
    model.add_callback("on_train_batch_end", batch)
    model.add_callback("on_fit_epoch_end", epoch)
    model.add_callback("on_val_start", validation)


def _run(config: dict, emit) -> None:
    emit("phase", phase="loading")
    from ultralytics import YOLO, settings
    from ultralytics.data import utils
    from ultralytics.utils import plotting
    from matplotlib.font_manager import findfont

    # Use installed fonts for preview rendering, without any network lookup.
    utils.check_font = lambda _name: None
    plotting.check_font = lambda name: findfont("Microsoft YaHei" if "Unicode" in str(name) else "DejaVu Sans")
    integrations = ("sync", "clearml", "comet", "dvc", "mlflow", "neptune", "raytune", "tensorboard", "wandb")
    settings.update({key: False for key in integrations if key in settings})
    emit("environment", versions={name: version(name) for name in ("torch", "torchvision", "ultralytics")})
    model = YOLO(config["model"])
    if model.task != config["task"]:
        emit("failure", code="WEIGHT_TASK_MISMATCH", summary=f"模型类型为 {model.task}，任务为 {config['task']}。")
        raise ValueError("训练任务与模型类型不匹配")
    model_args = {**config["arguments"], "device": "cpu", "amp": False, "workers": 0, "save": True,
                  "project": config["directory"], "name": "output", "exist_ok": True,
                  "data": config["data"], "plots": False}
    _callbacks(model, emit)
    result = model.train(**model_args)
    for thread in threads():
        if thread.name.endswith("(plot_images)"):
            thread.join(timeout=5)
    if result is not None:
        emit("final_metrics", values=_values(result.results_dict))


def _watch_parent() -> None:
    # Non-Windows hosts use the parent pipe and a separate process group.
    sys.stdin.buffer.read(1)
    os.killpg(os.getpgrp(), signal.SIGKILL)


def main() -> int:
    if sys.stdin.buffer.readline() != b"start\n":
        return 1  # do not train before the worker has attached process ownership
    if os.name != "nt":
        Thread(target=_watch_parent, daemon=True).start()
    directory = Path(sys.argv[1]).resolve()
    config = json.loads((directory / "invocation.json").read_text(encoding="utf-8"))
    with (directory / "events.jsonl").open("a", encoding="utf-8", buffering=1) as events:
        def emit(kind: str, **payload) -> None:
            events.write(json.dumps(dict(kind=kind, **payload), ensure_ascii=False, default=str, allow_nan=False) + "\n")

        try:
            _run(config, emit)
            return 0
        except Exception:
            traceback.print_exc()
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
