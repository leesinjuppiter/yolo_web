import os
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from app.training.schemas import TASK_TYPES, TrainingConfig

CPU = {"id": "cpu", "name": "本机 CPU", "kind": "cpu"}
_OPTIMIZERS = ["AdamW", "SGD", "Adam"]
_SUFFIX = {"detect": "", "segment": "-seg", "obb": "-obb", "classify": "-cls"}


@dataclass(frozen=True)
class ModelOption:
    id: str
    name: str
    architecture: str
    task: str
    source: str
    pretrained: bool

    def public(self) -> dict:
        return {
            "id": self.id, "name": self.name, "architecture": self.architecture,
            "task": self.task, "pretrained": self.pretrained,
        }


def available_models() -> list[ModelOption]:
    models = []
    directory = os.environ.get("WORKBENCH_TRAINING_WEIGHTS_DIR")
    root = Path(directory).expanduser().resolve() if directory else None
    for task in TASK_TYPES:
        base = "yolo11n" + _SUFFIX[task]
        models.append(ModelOption(base, f"{base} · 从零训练", "YOLO11", task, base + ".yaml", False))
        if root is not None:
            checkpoint = (root / (base + ".pt")).resolve()
            if checkpoint.is_relative_to(root) and checkpoint.is_file():
                models.append(ModelOption(checkpoint.name, f"{base} · 本地预训练", "YOLO11",
                                          task, str(checkpoint), True))
    return models


def resolve_model(model_id: str) -> ModelOption:
    for model in available_models():
        if model.id == model_id:
            return model
    raise ValueError("模型不可用，请选择已列出的本机模型")


def expand_arguments(config: dict) -> dict:
    parsed = TrainingConfig.model_validate(config)
    return {
        "epochs": parsed.epochs, "batch": parsed.batchSize, "imgsz": parsed.imageSize,
        "optimizer": parsed.optimizer, "lr0": parsed.learningRate, "lrf": parsed.finalLearningRate,
        "seed": parsed.seed, "patience": parsed.patience, "amp": False, "workers": 0,
        "deterministic": True, "save": True, "plots": False,
    }


def options() -> dict:
    return {"models": [model.public() for model in available_models()], "devices": [CPU],
            "optimizers": _OPTIMIZERS,
            "augmentations": [{"id": "standard", "name": "标准增强",
                               "description": "使用当前 Ultralytics 版本的任务默认增强参数"}]}


def engine_name() -> str:
    try:
        return f"Ultralytics {version('ultralytics')} · CPU"
    except PackageNotFoundError:
        return "Ultralytics 未安装 · CPU"

