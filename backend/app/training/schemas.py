from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.dataset.schemas import Name, TASK_ANNOTATION

TrainingType = Literal["detect", "segment", "obb", "classify"]
Status = Literal["created", "queued", "running", "succeeded", "failed", "canceled"]
Sort = Literal["newest", "progress", "metric", "duration"]
ACTIVE = ("created", "queued", "running")
TERMINAL = ("succeeded", "failed", "canceled")
TASK_TYPES = tuple(task for task in TASK_ANNOTATION if task != "pose")
QUALITY_METRIC = {"detect": "map50_95", "segment": "maskMap50_95", "obb": "map50_95", "classify": "top1"}


class TrainingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    name: Name
    datasetId: UUID
    task: TrainingType
    modelId: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    deviceId: Annotated[str, StringConstraints(pattern=r"^(cpu|cuda:(0|[1-9][0-9]*))$")]
    epochs: Annotated[int, Field(strict=True, ge=1, le=10000)]
    batchSize: Annotated[int, Field(strict=True, ge=1, le=1024)]
    imageSize: Annotated[int, Field(strict=True, ge=32, le=4096)]
    optimizer: Literal["AdamW", "SGD", "Adam"]
    learningRate: Annotated[float, Field(gt=0, le=1)]
    finalLearningRate: Annotated[float, Field(gt=0, le=1)]
    seed: Annotated[int, Field(strict=True, ge=0, le=2147483647)]
    patience: Annotated[int, Field(strict=True, ge=0, le=10000)]
    amp: bool = False
    freeze: Annotated[int, Field(strict=True, ge=0, le=1000)] = 0
    workers: Annotated[int, Field(strict=True, ge=0, le=32)] = 0
    augmentation: Literal["standard"]

    @model_validator(mode="after")
    def check_device_parameters(self):
        if self.deviceId == "cpu" and self.amp:
            raise ValueError("CPU 训练不支持启用 AMP，请关闭 AMP 或选择 CUDA 设备")
        return self

    @field_validator("imageSize")
    @classmethod
    def check_size(cls, value: int) -> int:
        if value % 32:
            raise ValueError("图像尺寸必须为 32 的倍数")
        return value

