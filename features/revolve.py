"""Parametric revolve feature."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import tau

from ..core.feature import Feature
from ..core.references import AxisReference


@dataclass
class RevolveFeature(Feature):
    feature_type: str = field(default="REVOLVE", init=False)
    sketch_id: str = ""
    axis_reference: AxisReference = field(default_factory=AxisReference)
    angle: float = tau
    operation: str = "NEW"

    def __post_init__(self) -> None:
        if self.sketch_id and self.sketch_id not in self.dependencies:
            self.dependencies.insert(0, self.sketch_id)
        axis_sketch_id = self.axis_reference.sketch_id
        if (
            self.axis_reference.reference_type == "SKETCH_LINE"
            and axis_sketch_id
            and axis_sketch_id not in self.dependencies
        ):
            self.dependencies.append(axis_sketch_id)
