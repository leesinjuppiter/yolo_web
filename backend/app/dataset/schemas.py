from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.annotation.schemas import Annotation, ImageStatus

TaskType = Literal["detect", "segment", "obb", "pose", "classify"]
Split = Literal["train", "val", "test"]
TASK_ANNOTATION = {"detect": "bbox", "segment": "polygon", "obb": "obb", "pose": "pose", "classify": "classify"}
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetCreate(RequestModel):
    name: Name
    task_type: TaskType
    keypoint_names: Annotated[list[Name], Field(max_length=100)] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_keypoint_names(self):
        if self.task_type == "pose" and not self.keypoint_names:
            raise ValueError("姿态数据集至少需要一个关键点名称")
        if self.task_type != "pose" and self.keypoint_names:
            raise ValueError("只有姿态数据集可以定义关键点")
        if len({name.casefold() for name in self.keypoint_names}) != len(self.keypoint_names):
            raise ValueError("关键点名称不能重复")
        return self


class ClassValues(RequestModel):
    name: Name
    color: Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]


class ClassInput(ClassValues):
    id: UUID


class ClassResponse(ClassInput):
    index: int


class ClassUpdate(ClassValues):
    previous: ClassValues


class ImageResponse(BaseModel):
    id: UUID
    name: str
    width: int
    height: int
    split: Split | None
    status: ImageStatus
    version: int
    url: str
    annotations: list[Annotation]


class DatasetResponse(BaseModel):
    id: UUID
    name: str
    task_type: TaskType
    created_at: datetime
    keypoint_names: list[str]
    classes: list[ClassResponse]
    images: list[ImageResponse]


class SplitUpdate(RequestModel):
    splits: dict[UUID, Split | None]

    @field_validator("splits")
    @classmethod
    def check_size(cls, splits):
        if not splits:
            raise ValueError("至少选择一张图片")
        return splits


class AnnotationSave(RequestModel):
    version: Annotated[int, Field(ge=0)]
    status: ImageStatus
    annotations: Annotated[list[Annotation], Field(max_length=5000)]
    classes: Annotated[list[ClassInput], Field(max_length=2000)]
