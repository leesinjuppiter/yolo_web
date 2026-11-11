import os
import json
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from app.training.schemas import TASK_TYPES, TrainingConfig
from app.training.devices import CPU, capabilities

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
    source_type: str = "architecture"
    sha256: str | None = None
    source_url: str | None = None
    pretraining_dataset: str | None = None

    def public(self) -> dict:
        return {
            "id": self.id, "name": self.name, "architecture": self.architecture,
            "task": self.task, "pretrained": self.pretrained, "sourceType": self.source_type,
            "sourceUrl": self.source_url, "pretrainingDataset": self.pretraining_dataset,
        }


def available_models() -> list[ModelOption]:
    models = []
    directory = os.environ.get("WORKBENCH_TRAINING_WEIGHTS_DIR")
    root = Path(directory).expanduser().resolve() if directory else None
    try:
        official = json.loads((root / "official-yolo11.json").read_text())["models"] if root else {}
    except (OSError, ValueError, KeyError):
        official = {}
    for task in TASK_TYPES:
        for scale in "nsmlx":
            base = "yolo11" + scale + _SUFFIX[task]
            models.append(ModelOption(base, f"{base} · 从零训练", "YOLO11", task, base + ".yaml", False))
        if root is not None:
            for scale in "nsmlx":
                name = "yolo11" + scale + _SUFFIX[task]
                checkpoint = (root / (name + ".pt")).resolve()
                if not checkpoint.is_relative_to(root) or not checkpoint.is_file():
                    continue
                metadata = official.get(checkpoint.name, {})
                if metadata and (metadata.get("task") != task or metadata.get("sizeBytes") != checkpoint.stat().st_size):
                    continue
                models.append(ModelOption(checkpoint.name,
                    f"{name} · 官方预训练（{metadata['dataset']}）" if metadata else f"{name} · 本地预训练",
                    "YOLO11", task, str(checkpoint), True,
                    "official_weights" if metadata else "local_weights", metadata.get("sha256"),
                    metadata.get("url"), metadata.get("dataset")))
    return models


def resolve_model(model_id: str) -> ModelOption:
    for model in available_models():
        if model.id == model_id:
            return model
    raise ValueError("模型不可用，请选择已列出的本机模型")


def validate_model_config(config: TrainingConfig, model: ModelOption) -> None:
    if model.task != config.task:
        raise ValueError("所选模型与训练任务类型不匹配")
    if config.freeze and not model.pretrained:
        raise ValueError("从零训练不能冻结随机初始化层，请选择预训练模型或将冻结层数设为 0")


def expand_arguments(config: dict) -> dict:
    parsed = TrainingConfig.model_validate(config)
    return {
        "epochs": parsed.epochs, "batch": parsed.batchSize, "imgsz": parsed.imageSize,
        "optimizer": parsed.optimizer, "lr0": parsed.learningRate, "lrf": parsed.finalLearningRate,
        "seed": parsed.seed, "patience": parsed.patience, "amp": parsed.amp, "workers": parsed.workers,
        "freeze": parsed.freeze, "device": parsed.deviceId,
        "deterministic": True, "save": True, "plots": False,
    }


def options() -> dict:
    return {"models": [model.public() for model in available_models()], **capabilities(),
            "optimizers": _OPTIMIZERS,
            "augmentations": [{"id": "standard", "name": "标准增强",
                               "description": "使用当前 Ultralytics 版本的任务默认增强参数"}]}


def engine_name() -> str:
    try:
        return f"Ultralytics {version('ultralytics')}"
    except PackageNotFoundError:
        return "Ultralytics 未安装"
