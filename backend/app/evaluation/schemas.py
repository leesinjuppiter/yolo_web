from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    versionId: UUID
    deviceId: Literal["cpu"] = "cpu"
    imgsz: int = Field(default=640, ge=32, le=2048)
    purpose: Literal["final", "diagnostic"] = "final"
    sourceTaskId: UUID | None = None
    diagnosticConf: float = Field(default=0.25, gt=0, le=1)
    diagnosticIou: float = Field(default=0.5, gt=0, le=1)


class MetadataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    displayName: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    versionIds: list[UUID] = Field(min_length=2, max_length=4)
    baselineId: UUID
