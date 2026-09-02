"""Sketch feature definitions and plane coordinate utilities."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from ..core.feature import Feature
from .entities import SketchEntity
from .plane import PLANE_AXES, ResolvedPlane, SketchPlaneReference
from ..core.references import TopoReference

Vector3 = tuple[float, float, float]

@dataclass
class SketchFeature(Feature):
    """A planar collection of entities expressed in local (u, v) coordinates."""

    feature_type: str = field(default="SKETCH", init=False)
    plane_reference: SketchPlaneReference = field(default_factory=SketchPlaneReference)
    origin: Vector3 = (0.0, 0.0, 0.0)
    x_axis: Vector3 = (1.0, 0.0, 0.0)
    y_axis: Vector3 = (0.0, 1.0, 0.0)
    entities: list[SketchEntity] = field(default_factory=list)
    # Region IDs are derived from the boundary entity UUIDs.  They are
    # persistent sketch edits, not Blender mesh/polygon indices.
    deleted_regions: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.plane_reference.reference_type == "DATUM":
            plane_type = self.plane_reference.datum_plane or "XY"
            if plane_type in PLANE_AXES:
                self.x_axis, self.y_axis = PLANE_AXES[plane_type]
        elif self.plane_reference.feature_id and not self.dependencies:
            self.dependencies = [self.plane_reference.feature_id]

    @property
    def plane_type(self) -> str:
        if self.plane_reference.reference_type == "DATUM":
            return self.plane_reference.datum_plane or "XY"
        return "FEATURE_PLANE"

    @classmethod
    def on_plane(
        cls, name: str, plane_type: str, offset: float = 0.0
    ) -> "SketchFeature":
        if plane_type not in PLANE_AXES:
            raise ValueError(f"Unsupported datum plane: {plane_type}")
        x_axis, y_axis = PLANE_AXES[plane_type]
        return cls(
            name=name,
            plane_reference=SketchPlaneReference(
                "DATUM", datum_plane=plane_type, offset=offset
            ),
            x_axis=x_axis,
            y_axis=y_axis,
        )

    @classmethod
    def on_feature_plane(
        cls, name: str, feature_id: str, role: str = "END_PLANE", offset: float = 0.0
    ) -> "SketchFeature":
        return cls(
            name=name,
            plane_reference=SketchPlaneReference(
                "FEATURE_PLANE",
                datum_plane=None,
                feature_id=feature_id,
                role=role,
                offset=offset,
            ),
            dependencies=[feature_id],
        )

    @classmethod
    def on_face(
        cls, name: str, face: TopoReference, offset: float = 0.0
    ) -> "SketchFeature":
        if face.reference_type != "FACE":
            raise ValueError("Sketch support must be a face reference.")
        return cls(
            name=name,
            plane_reference=SketchPlaneReference(
                reference_type="FACE",
                datum_plane=None,
                feature_id=face.feature_id,
                role=face.role,
                source_entity_id=face.source_entity_id,
                offset=offset,
            ),
            dependencies=[face.feature_id],
        )

    def apply_resolved_plane(self, plane: ResolvedPlane) -> None:
        self.origin = plane.origin
        self.x_axis = plane.x_axis
        self.y_axis = plane.y_axis

    @property
    def plane_offset(self) -> float:
        """Persistent support-plane offset in meters."""

        return self.plane_reference.offset

    def set_plane_offset(self, offset: float) -> None:
        """Update the support offset while preserving its semantic reference."""

        self.plane_reference = replace(self.plane_reference, offset=float(offset))


def sketch_to_world(sketch: SketchFeature, u: float, v: float) -> Vector3:
    """Map 2D sketch coordinates to a 3D model-space point."""

    return tuple(
        sketch.origin[index]
        + u * sketch.x_axis[index]
        + v * sketch.y_axis[index]
        for index in range(3)
    )  # type: ignore[return-value]


def sketch_normal(sketch: SketchFeature) -> Vector3:
    x = sketch.x_axis
    y = sketch.y_axis
    return (
        x[1] * y[2] - x[2] * y[1],
        x[2] * y[0] - x[0] * y[2],
        x[0] * y[1] - x[1] * y[0],
    )
