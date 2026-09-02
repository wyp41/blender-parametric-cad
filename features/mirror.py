"""Parametric feature for mirroring one additive feature across a plane."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.feature import Feature
from ..sketch.plane import SketchPlaneReference


@dataclass
class MirrorFeature(Feature):
    """Mirror a supported additive source feature and union it with the body."""

    feature_type: str = field(default="MIRROR", init=False)
    source_feature_id: str = ""
    mirror_plane: SketchPlaneReference = field(
        default_factory=lambda: SketchPlaneReference("DATUM", datum_plane="YZ")
    )

    def __post_init__(self) -> None:
        if self.source_feature_id and self.source_feature_id not in self.dependencies:
            self.dependencies.insert(0, self.source_feature_id)
