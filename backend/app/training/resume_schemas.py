from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.dataset.schemas import Name


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    deviceId: Annotated[str, StringConstraints(pattern=r"^(cpu|cuda:[0-9]+)$")] | None = None
    batchSize: Annotated[int, Field(strict=True, ge=1, le=1024)] | None = None
    workers: Annotated[int, Field(strict=True, ge=0, le=32)] | None = None
    amp: bool | None = None
