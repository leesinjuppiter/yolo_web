from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    versionId: UUID
    imgsz: int = Field(default=640, ge=32, le=2048)
    deviceId: Literal["cpu"] = "cpu"

    @field_validator("imgsz")
    @classmethod
    def image_stride(cls, value: int) -> int:
        if value % 32:
            raise ValueError("输入尺寸必须为 32 的整数倍")
        return value


class PackageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exportId: UUID
