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
        parameters = list(trainer.model.parameters())
        trainable = sum(parameter.numel() for parameter in parameters if parameter.requires_grad)
        if not trainable:
            raise ValueError("冻结配置未留下可训练参数")
        emit("environment", arguments={**vars(trainer.args), "amp": bool(trainer.amp)}, actualDevice=str(trainer.device),
             trainableParameters=trainable,
             frozenParameters=sum(parameter.numel() for parameter in parameters if not parameter.requires_grad))
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
    freeze = config["arguments"].get("freeze", 0)
    if freeze:
        modules = getattr(model.model, "model", None)
        if modules is None or freeze >= len(modules):
            emit("failure", code="FREEZE_INVALID", summary="冻结层数必须小于当前模型的模块数量")
            raise ValueError("冻结层数超出模型范围")
        if not config["arguments"].get("pretrained"):
            raise ValueError("不能冻结从零训练的随机初始化层")
    device = config["arguments"].get("device", "cpu")
    if device != "cpu":
        import torch

        index = int(device.split(":")[1])
        if not torch.cuda.is_available() or index >= torch.cuda.device_count():
            emit("failure", code="CUDA_UNAVAILABLE", summary="所选 CUDA 设备在训练启动时不可用")
            raise RuntimeError("所选 CUDA 设备不可用")
    model_args = {**config["arguments"], "device": device, "save": True,
                  "project": config["directory"], "name": "output", "exist_ok": True,
                  "data": config["data"], "plots": False}
    if config.get("resume"):
        model_args.update(resume=config["model"], save_dir=str(Path(config["directory"]) / "output"))
    _callbacks(model, emit)
    result = model.train(**model_args)
    for thread in threads():
        if thread.name.endswith("(plot_images)"):
            thread.join(timeout=5)
    if result is not None:
        emit("final_metrics", values=_values(result.results_dict))
    emit("phase", phase="archiving")
    from app.training.previews import generate_previews

    try:
        generate_previews(Path(config["directory"]), device=device)
    except Exception as exc:
        print(f"WARNING: 单张验证预览生成失败，保留训练结果：{exc}", flush=True)


def _watch_parent() -> None:
    # Non-Windows hosts use the parent pipe and a separate process group.
    os.read(sys.stdin.fileno(), 1)
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
