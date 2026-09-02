"""Parametric rigid transform feature."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.feature import Feature
from ..core.transform import Transform, Vector3, validate_vector


@dataclass
class TransformFeature(Feature):
    """Transform the current Part body and its downstream reference frame."""

    feature_type: str = field(default="TRANSFORM", init=False)
    translation: Vector3 = (0.0, 0.0, 0.0)
    rotation: Vector3 = (0.0, 0.0, 0.0)

    def __post_init__(self) -> None:
        self.translation = validate_vector(self.translation, "Translation")
        self.rotation = validate_vector(self.rotation, "Rotation")

    def as_transform(self) -> Transform:
        return Transform(self.translation, self.rotation)
