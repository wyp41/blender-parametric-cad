"""Semantic sketch-plane references and Blender-independent resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

Vector3 = tuple[float, float, float]

PLANE_AXES: dict[str, tuple[Vector3, Vector3]] = {
    "XY": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
    "XZ": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "YZ": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
}


@dataclass(frozen=True)
class SketchPlaneReference:
    """Stable reference to a datum or semantic feature-generated plane."""

    reference_type: str = "DATUM"
    datum_plane: str | None = "XY"
    feature_id: str | None = None
    role: str | None = None


@dataclass(frozen=True)
class ResolvedPlane:
    origin: Vector3
    x_axis: Vector3
    y_axis: Vector3
    normal: Vector3


class PlaneResolutionError(ValueError):
    pass


class PlaneResolver:
    """Resolve semantic planes entirely from CAD history parameters."""

    def resolve(self, reference: SketchPlaneReference, context: Any) -> ResolvedPlane:
        if reference.reference_type == "DATUM":
            if reference.datum_plane not in PLANE_AXES:
                raise PlaneResolutionError(f"Unsupported datum plane: {reference.datum_plane}")
            x_axis, y_axis = PLANE_AXES[reference.datum_plane]
            return ResolvedPlane((0.0, 0.0, 0.0), x_axis, y_axis, _cross(x_axis, y_axis))

        if reference.reference_type != "FEATURE_PLANE":
            raise PlaneResolutionError(
                f"Unsupported plane reference type: {reference.reference_type}"
            )
        if reference.role != "END_PLANE" or not reference.feature_id:
            raise PlaneResolutionError("Only Extrude END_PLANE is supported.")

        from ..features.extrude import ExtrudeFeature

        feature = context.evaluated_features.get(reference.feature_id)
        if not isinstance(feature, ExtrudeFeature):
            raise PlaneResolutionError("Referenced Extrude feature is not evaluated.")
        if feature.operation != "NEW":
            raise PlaneResolutionError("END_PLANE requires a NEW Extrude feature.")
        source_plane = context.resolved_planes.get(feature.sketch_id)
        if source_plane is None:
            raise PlaneResolutionError("Source sketch plane is not resolved.")
        offset = feature.distance * feature.direction
        origin = tuple(
            source_plane.origin[index] + source_plane.normal[index] * offset
            for index in range(3)
        )
        return ResolvedPlane(
            origin, source_plane.x_axis, source_plane.y_axis, source_plane.normal
        )


def resolve_sketch_plane_from_history(part: Any, sketch_id: str) -> ResolvedPlane:
    """Resolve a sketch for editing without evaluating or inspecting Blender geometry."""

    from ..features.extrude import ExtrudeFeature
    from .sketch import SketchFeature

    @dataclass
    class Context:
        evaluated_features: dict[str, Any]
        resolved_planes: dict[str, ResolvedPlane]

    context = Context({}, {})
    resolver = PlaneResolver()
    for feature in part.features:
        if feature.suppressed:
            if feature.id == sketch_id:
                raise PlaneResolutionError("Suppressed sketch has no active plane.")
            continue
        if isinstance(feature, SketchFeature):
            plane = resolver.resolve(feature.plane_reference, context)
            context.resolved_planes[feature.id] = plane
            context.evaluated_features[feature.id] = feature
            if feature.id == sketch_id:
                return plane
        elif isinstance(feature, ExtrudeFeature):
            if feature.sketch_id in context.resolved_planes and feature.distance > 0.0:
                context.evaluated_features[feature.id] = feature
    raise PlaneResolutionError("Sketch plane could not be resolved from feature history.")


def _cross(x_axis: Vector3, y_axis: Vector3) -> Vector3:
    return (
        x_axis[1] * y_axis[2] - x_axis[2] * y_axis[1],
        x_axis[2] * y_axis[0] - x_axis[0] * y_axis[2],
        x_axis[0] * y_axis[1] - x_axis[1] * y_axis[0],
    )
