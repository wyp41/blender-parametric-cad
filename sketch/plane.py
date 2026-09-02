"""Semantic sketch-plane references and Blender-independent resolution."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Any

from ..core.transform import (
    IDENTITY_MATRIX,
    Matrix4,
    matrix_multiply,
    transform_point,
    transform_vector,
)

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
    source_entity_id: str | None = None
    # Offset along the resolved plane normal, stored in meters.
    offset: float = 0.0


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
            plane = ResolvedPlane((0.0, 0.0, 0.0), x_axis, y_axis, _cross(x_axis, y_axis))
            frame_matrix = getattr(context, "frame_matrix", IDENTITY_MATRIX)
            plane = _transform_plane(plane, frame_matrix)
        elif reference.reference_type == "FACE":
            plane = self._resolve_face(reference, context)
        elif reference.reference_type == "FEATURE_PLANE":
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
            support_offset = feature.distance * feature.direction
            origin = tuple(
                source_plane.origin[index] + source_plane.normal[index] * support_offset
                for index in range(3)
            )
            plane = ResolvedPlane(
                origin, source_plane.x_axis, source_plane.y_axis, source_plane.normal
            )
        else:
            raise PlaneResolutionError(
                f"Unsupported plane reference type: {reference.reference_type}"
            )

        try:
            offset = float(reference.offset)
        except (TypeError, ValueError) as exc:
            raise PlaneResolutionError("Sketch plane offset must be numeric.") from exc
        if not isfinite(offset):
            raise PlaneResolutionError("Sketch plane offset must be finite.")
        if abs(offset) <= 1e-15:
            return plane
        origin = tuple(
            plane.origin[index] + plane.normal[index] * offset for index in range(3)
        )
        return ResolvedPlane(origin, plane.x_axis, plane.y_axis, plane.normal)

    def _resolve_face(
        self, reference: SketchPlaneReference, context: Any
    ) -> ResolvedPlane:
        from ..features.extrude import ExtrudeFeature
        from ..sketch.entities import SketchLine
        from ..sketch.sketch import sketch_to_world

        if reference.role not in {"START_FACE", "END_FACE", "SIDE_FACE"}:
            raise PlaneResolutionError("Unsupported Extrude face role.")
        if not reference.feature_id:
            raise PlaneResolutionError("Face reference has no source Extrude feature.")
        feature = context.evaluated_features.get(reference.feature_id)
        if not isinstance(feature, ExtrudeFeature):
            raise PlaneResolutionError("Referenced Extrude feature is not evaluated.")
        if feature.operation != "NEW":
            raise PlaneResolutionError(
                "Only faces from simple NEW Extrude features are supported."
            )
        source = context.evaluated_features.get(feature.sketch_id)
        source_plane = context.resolved_planes.get(feature.sketch_id)
        if source is None or source_plane is None:
            raise PlaneResolutionError("Source sketch plane is not resolved.")

        if reference.role == "START_FACE":
            return source_plane
        if reference.role == "END_FACE":
            offset = feature.distance * feature.direction
            origin = tuple(
                source_plane.origin[index] + source_plane.normal[index] * offset
                for index in range(3)
            )
            return ResolvedPlane(
                origin, source_plane.x_axis, source_plane.y_axis, source_plane.normal
            )

        if reference.source_entity_id is None:
            raise PlaneResolutionError("SIDE_FACE requires a source SketchLine.")
        line = next(
            (
                entity
                for entity in source.entities
                if isinstance(entity, SketchLine)
                and entity.id == reference.source_entity_id
            ),
            None,
        )
        if line is None:
            raise PlaneResolutionError("Referenced side-face SketchLine is unavailable.")
        start = sketch_to_world(source, line.x1, line.y1)
        end = sketch_to_world(source, line.x2, line.y2)
        x_axis = _normalize(tuple(end[index] - start[index] for index in range(3)))
        y_axis = tuple(
            source_plane.normal[index] * feature.direction for index in range(3)
        )
        return ResolvedPlane(start, x_axis, y_axis, _cross(x_axis, y_axis))


def resolve_sketch_plane_from_history(part: Any, sketch_id: str) -> ResolvedPlane:
    """Resolve a sketch for editing without evaluating or inspecting Blender geometry."""

    from ..features.extrude import ExtrudeFeature
    from ..features.transform import TransformFeature
    from .sketch import SketchFeature

    @dataclass
    class Context:
        evaluated_features: dict[str, Any]
        resolved_planes: dict[str, ResolvedPlane]
        frame_matrix: Matrix4 = IDENTITY_MATRIX

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
        elif isinstance(feature, TransformFeature):
            if context.evaluated_features:
                try:
                    transform = feature.as_transform()
                except (TypeError, ValueError) as exc:
                    raise PlaneResolutionError(f"Invalid Transform feature: {exc}") from exc
                context.frame_matrix = matrix_multiply(
                    transform.matrix, context.frame_matrix
                )
                for resolved_id, plane in list(context.resolved_planes.items()):
                    updated = _transform_plane(plane, transform.matrix)
                    context.resolved_planes[resolved_id] = updated
                    source = context.evaluated_features.get(resolved_id)
                    if isinstance(source, SketchFeature):
                        source.apply_resolved_plane(updated)
                context.evaluated_features[feature.id] = feature
    raise PlaneResolutionError("Sketch plane could not be resolved from feature history.")


def _cross(x_axis: Vector3, y_axis: Vector3) -> Vector3:
    return (
        x_axis[1] * y_axis[2] - x_axis[2] * y_axis[1],
        x_axis[2] * y_axis[0] - x_axis[0] * y_axis[2],
        x_axis[0] * y_axis[1] - x_axis[1] * y_axis[0],
    )


def _normalize(vector: Vector3) -> Vector3:
    length = sqrt(sum(value * value for value in vector))
    if length <= 1e-12:
        raise PlaneResolutionError("Referenced SketchLine has zero length.")
    return tuple(value / length for value in vector)  # type: ignore[return-value]


def _transform_plane(plane: ResolvedPlane, matrix: Matrix4) -> ResolvedPlane:
    """Apply a rigid history transform to a resolved semantic plane."""

    return ResolvedPlane(
        transform_point(matrix, plane.origin),
        transform_vector(matrix, plane.x_axis),
        transform_vector(matrix, plane.y_axis),
        transform_vector(matrix, plane.normal),
    )
