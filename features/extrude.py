"""Parametric extrusion feature."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.feature import Feature


@dataclass
class ExtrudeFeature(Feature):
    feature_type: str = field(default="EXTRUDE", init=False)
    sketch_id: str = ""
    distance: float = 0.020
    direction: int = 1
    operation: str = "NEW"
    depth_mode: str = "BLIND"

    def __post_init__(self) -> None:
        if self.sketch_id and not self.dependencies:
            self.dependencies = [self.sketch_id]
