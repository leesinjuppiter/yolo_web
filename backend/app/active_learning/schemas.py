from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.annotation.schemas import Annotation
from app.dataset.schemas import Name


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class IterationRequest(Request):
    name: Name
    goal: str = Field(default="", max_length=2000)
    datasetId: UUID
    baselineVersionId: UUID


class RecommendationRequest(Request):
    iterationId: UUID
    strategy: Literal["error_first", "low_confidence", "mixed"] = "mixed"
    evaluationId: UUID | None = None
    deviceId: str = Field(default="cpu", pattern=r"^(cpu|cuda:(0|[1-9][0-9]*))$")
    imageSize: int = Field(default=640, ge=32, le=2048, multiple_of=32)
    retainConfidence: float = Field(default=.05, ge=0, le=1)
    minConfidence: float = Field(default=.05, ge=0, le=1)
    maxConfidence: float = Field(default=.5, gt=0, le=1)
    nmsIou: float = Field(default=.7, gt=0, le=1)
    referenceLimit: int = Field(default=50, ge=1, le=1000)
    candidateLimit: int = Field(default=50, ge=1, le=1000)
    includeNoPredictions: bool = False

    @model_validator(mode="after")
    def check_strategy(self):
        if not self.retainConfidence <= self.minConfidence < self.maxConfidence:
            raise ValueError("要求保留阈值 ≤ 低置信度下限 < 上限")
        if self.strategy != "low_confidence" and self.evaluationId is None:
            raise ValueError("错误优先/混合推荐需要已完成的 val 诊断")
        return self


class SelectionRequest(Request):
    candidateIds: list[UUID] = Field(min_length=1, max_length=1000)
    selected: bool


class AddCandidatesRequest(Request):
    imageIds: list[UUID] = Field(min_length=1, max_length=1000)
    reason: str = Field(default="manual_revision", max_length=120)


class ReferencesRequest(Request):
    referenceIds: list[UUID] = Field(max_length=100)


class ReviewRequest(Request):
    version: int = Field(ge=0)
    annotations: list[Annotation]
    status: Literal["annotated", "negative"]
    negativeConfirmed: bool = False


class ResultRequest(Request):
    versionId: UUID
    baselineEvaluationId: UUID
    resultEvaluationId: UUID
