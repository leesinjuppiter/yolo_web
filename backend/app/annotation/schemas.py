from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

AnnotationSource = Literal["manual", "sam", "imported"]
ImageStatus = Literal["unlabeled", "negative", "annotated"]


class ShapeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Rectangle(ShapeModel):
    x: FiniteFloat
    y: FiniteFloat
    width: Annotated[FiniteFloat, Field(gt=0)]
    height: Annotated[FiniteFloat, Field(gt=0)]


class RotatedRectangle(ShapeModel):
    cx: FiniteFloat
    cy: FiniteFloat
    width: Annotated[FiniteFloat, Field(gt=0)]
    height: Annotated[FiniteFloat, Field(gt=0)]
    angle: FiniteFloat


class Keypoint(ShapeModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    x: FiniteFloat
    y: FiniteFloat
    visible: Literal[0, 1, 2]


class AnnotationBase(ShapeModel):
    id: UUID
    class_id: UUID
    class_index: Annotated[int, Field(ge=0)] | None = None
    source: AnnotationSource = "manual"


class BoundingBox(AnnotationBase):
    type: Literal["bbox"]
    bbox: Rectangle


class Polygon(AnnotationBase):
    type: Literal["polygon"]
    polygon: Annotated[list[tuple[FiniteFloat, FiniteFloat]], Field(min_length=3, max_length=4000)]


class OrientedBox(AnnotationBase):
    type: Literal["obb"]
    obb: RotatedRectangle


class Pose(AnnotationBase):
    type: Literal["pose"]
    bbox: Rectangle
    keypoints: Annotated[list[Keypoint], Field(max_length=100)]


class Classification(AnnotationBase):
    type: Literal["classify"]


Annotation = Annotated[
    BoundingBox | Polygon | OrientedBox | Pose | Classification,
    Field(discriminator="type"),
]
