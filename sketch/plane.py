"""Semantic sketch-plane references and Blender-independent resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import cos, isfinite, sin, sqrt, tau
from typing import Any
from ..core.references import FaceReference

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


# Runtime-only contexts let Blender's sketch overlay and edit tools reuse the
# last rebuild's derived candidates. The registry is never serialized.
_RUNTIME_EVALUATIONS: dict[str, Any] = {}


def register_runtime_evaluation(part_id: str, context: Any) -> None:
    if context is not None:
        _RUNTIME_EVALUATIONS[str(part_id)] = context


def clear_runtime_evaluation(part_id: str) -> None:
    _RUNTIME_EVALUATIONS.pop(str(part_id), None)


@dataclass(frozen=True)
class RegionHint:
    """Geometric disambiguation data for one connected planar region."""

    centroid: Vector3
    area: float

    def __post_init__(self) -> None:
        centroid = tuple(float(value) for value in self.centroid)
        if len(centroid) != 3 or not all(isfinite(value) for value in centroid):
            raise ValueError("Region centroid must contain three finite numbers.")
        area = float(self.area)
        if not isfinite(area) or area < 0.0:
            raise ValueError("Region area must be a finite non-negative number.")
        object.__setattr__(self, "centroid", centroid)
        object.__setattr__(self, "area", area)

    def to_dict(self) -> dict[str, Any]:
        return {"centroid": list(self.centroid), "area": self.area}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "RegionHint | None":
        if not data:
            return None
        return cls(
            centroid=tuple(float(value) for value in data.get("centroid", ())),
            area=float(data.get("area", 0.0)),
        )


@dataclass(frozen=True)
class PlaneReference:
    """Stable reference to a datum, semantic, or Boolean-derived plane."""

    reference_type: str = "DATUM"
    datum_plane: str | None = "XY"
    feature_id: str | None = None
    role: str | None = None
    source_entity_id: str | None = None
    # Offset along the resolved plane normal, stored in meters.
    offset: float = 0.0
    face_reference: FaceReference | None = None
    # M7 derived-plane identity.  These fields are intentionally separate from
    # ``offset``: offset is an editable Sketch support offset, while
    # ``local_offset`` is part of the derived face identity.
    producer_feature_id: str | None = None
    local_normal: Vector3 | None = None
    local_offset: float | None = None
    source_feature_ids: tuple[str, ...] = ()
    region_hint: RegionHint | None = None

    def __post_init__(self):
        if self.face_reference is not None:
            object.__setattr__(self, "feature_id", self.face_reference.feature_id)
            object.__setattr__(self, "role", self.face_reference.role)
            object.__setattr__(self, "source_entity_id", self.face_reference.source_entity_id)
        elif self.reference_type == "FACE" and self.feature_id:
            object.__setattr__(self, "face_reference", FaceReference(
                self.feature_id, self.role, self.source_entity_id))
        elif self.reference_type == "DERIVED_PLANE":
            producer = self.producer_feature_id or self.feature_id
            if not producer:
                raise ValueError("Derived plane reference requires a producer feature UUID.")
            if self.local_normal is None or self.local_offset is None:
                raise ValueError("Derived plane reference requires local plane geometry.")
            normal, plane_offset = canonical_plane(
                self.local_normal, float(self.local_offset)
            )
            object.__setattr__(self, "producer_feature_id", str(producer))
            object.__setattr__(self, "feature_id", str(producer))
            object.__setattr__(self, "datum_plane", None)
            object.__setattr__(self, "role", "DERIVED_PLANE")
            object.__setattr__(self, "source_entity_id", None)
            object.__setattr__(self, "local_normal", normal)
            object.__setattr__(self, "local_offset", plane_offset)
            object.__setattr__(
                self,
                "source_feature_ids",
                tuple(dict.fromkeys(str(value) for value in self.source_feature_ids if value)),
            )


@dataclass(frozen=True, init=False)
class DerivedPlaneReference(PlaneReference):
    """Convenience constructor for the derived form of ``PlaneReference``."""

    reference_type: str = "DERIVED_PLANE"

    def __init__(
        self,
        producer_feature_id: str,
        local_normal: Vector3,
        local_offset: float,
        source_feature_ids: tuple[str, ...] | list[str] = (),
        region_hint: RegionHint | None = None,
        offset: float = 0.0,
    ) -> None:
        object.__setattr__(self, "reference_type", "DERIVED_PLANE")
        object.__setattr__(self, "datum_plane", None)
        object.__setattr__(self, "feature_id", str(producer_feature_id))
        object.__setattr__(self, "role", "DERIVED_PLANE")
        object.__setattr__(self, "source_entity_id", None)
        object.__setattr__(self, "offset", float(offset))
        object.__setattr__(self, "face_reference", None)
        object.__setattr__(self, "producer_feature_id", str(producer_feature_id))
        object.__setattr__(self, "local_normal", tuple(local_normal))
        object.__setattr__(self, "local_offset", float(local_offset))
        object.__setattr__(self, "source_feature_ids", tuple(source_feature_ids))
        object.__setattr__(self, "region_hint", region_hint)
        PlaneReference.__post_init__(self)


def canonical_plane(normal: Vector3, offset: float) -> tuple[Vector3, float]:
    """Canonicalize equivalent ``n·x = d`` planes to one sign."""

    values = tuple(float(value) for value in normal)
    length = sqrt(sum(value * value for value in values))
    if len(values) != 3 or length <= 1e-12 or not all(isfinite(value) for value in values):
        raise ValueError("Plane normal must contain three finite non-zero numbers.")
    normalized = tuple(value / length for value in values)
    plane_offset = float(offset) / length
    for value in normalized:
        if abs(value) <= 1e-12:
            continue
        if value < 0.0:
            normalized = tuple(-component for component in normalized)
            plane_offset = -plane_offset
        break
    if not isfinite(plane_offset):
        raise ValueError("Plane offset must be finite.")
    return normalized, plane_offset


SketchPlaneReference = PlaneReference


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
        if reference.reference_type == "DERIVED_PLANE":
            plane = self._resolve_derived(reference, context)
            return self._apply_offset(reference, plane)
        semantic = getattr(context, "semantic_planes", {}).get(
            (reference.feature_id, reference.role, reference.source_entity_id))
        if semantic is not None and reference.reference_type != "DATUM":
            plane = semantic
        elif reference.reference_type == "DATUM":
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

        return self._apply_offset(reference, plane)

    def _resolve_derived(
        self, reference: SketchPlaneReference, context: Any
    ) -> ResolvedPlane:
        from .planar_faces import derived_reference_status

        producer = reference.producer_feature_id or reference.feature_id
        candidates = getattr(context, "derived_plane_candidates", {}).get(producer, ())
        if not candidates:
            raise PlaneResolutionError(
                "Derived planar face reference is missing after rebuild."
            )
        matched, status = derived_reference_status(reference, candidates)
        if matched is None:
            raise PlaneResolutionError(
                "Derived planar face reference is missing after rebuild."
                if status == "MISSING"
                else "This planar face reference is ambiguous after rebuild."
            )
        return matched.plane

    @staticmethod
    def _apply_offset(
        reference: SketchPlaneReference, plane: ResolvedPlane
    ) -> ResolvedPlane:
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
        from ..features.revolve import RevolveFeature
        from ..sketch.entities import SketchLine

        if reference.role in {"START_CAP", "END_CAP"}:
            if not reference.feature_id:
                raise PlaneResolutionError("Revolve cap reference has no source feature.")
            feature = context.evaluated_features.get(reference.feature_id)
            if not isinstance(feature, RevolveFeature):
                raise PlaneResolutionError("Referenced Revolve feature is not evaluated.")
            plane = resolve_revolve_cap_planes(feature, context).get(
                (reference.role, reference.source_entity_id)
            )
            if plane is None:
                if abs(abs(feature.angle) - tau) <= 1e-9:
                    raise PlaneResolutionError(
                        "This full 360-degree Revolve has no supported planar profile cap "
                        "for the referenced SketchLine."
                    )
                raise PlaneResolutionError(
                    "Referenced Revolve cap is unavailable for the current profile."
                )
            return plane

        if reference.role not in {"START_FACE", "END_FACE", "SIDE_FACE"}:
            raise PlaneResolutionError("Unsupported generated face role.")
        if not reference.feature_id:
            raise PlaneResolutionError("Face reference has no source feature.")
        feature = context.evaluated_features.get(reference.feature_id)
        if not isinstance(feature, ExtrudeFeature):
            raise PlaneResolutionError("Referenced Extrude feature is not evaluated.")
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
        start = tuple(source_plane.origin[i] + line.x1 * source_plane.x_axis[i]
                      + line.y1 * source_plane.y_axis[i] for i in range(3))
        end = tuple(source_plane.origin[i] + line.x2 * source_plane.x_axis[i]
                    + line.y2 * source_plane.y_axis[i] for i in range(3))
        x_axis = _normalize(tuple(end[index] - start[index] for index in range(3)))
        y_axis = tuple(
            source_plane.normal[index] * feature.direction for index in range(3)
        )
        return ResolvedPlane(start, x_axis, y_axis, _cross(x_axis, y_axis))


def resolve_sketch_plane_from_history(part: Any, sketch_id: str) -> ResolvedPlane:
    """Resolve a sketch for editing without evaluating or inspecting Blender geometry."""

    from ..features.extrude import ExtrudeFeature
    from ..features.revolve import RevolveFeature
    from ..features.transform import TransformFeature
    from ..features.mirror import MirrorFeature
    from .planar_faces import propagate_planes
    from .sketch import SketchFeature

    target = part.get_feature(sketch_id)
    if isinstance(target, SketchFeature) and target.plane_reference.reference_type == "DERIVED_PLANE":
        runtime = _RUNTIME_EVALUATIONS.get(str(part.id))
        if runtime is not None:
            plane = runtime.resolved_planes.get(sketch_id)
            if plane is not None:
                return plane
            message = target.error_message or "Derived Sketch support is unavailable after rebuild."
            raise PlaneResolutionError(message)

    @dataclass
    class Context:
        evaluated_features: dict[str, Any]
        resolved_planes: dict[str, ResolvedPlane]
        frame_matrix: Matrix4 = IDENTITY_MATRIX
        semantic_planes: dict = field(default_factory=dict)

    context = Context({}, {})
    resolver = PlaneResolver()
    for index, feature in enumerate(part.features):
        if part.rollback_index is not None and index > part.rollback_index:
            raise PlaneResolutionError("Sketch is after the rollback point.")
        if feature.suppressed:
            if feature.id == sketch_id:
                raise PlaneResolutionError("Suppressed sketch has no active plane.")
            continue
        if any(dependency not in context.evaluated_features for dependency in feature.dependencies):
            raise PlaneResolutionError("Sketch support has an unavailable upstream dependency.")
        if isinstance(feature, SketchFeature):
            plane = resolver.resolve(feature.plane_reference, context)
            context.resolved_planes[feature.id] = plane
            context.evaluated_features[feature.id] = feature
            if feature.id == sketch_id:
                return plane
        elif isinstance(feature, ExtrudeFeature):
            if feature.sketch_id in context.resolved_planes and (
                feature.distance > 0.0 or feature.depth_mode == "THROUGH_ALL"
            ):
                context.evaluated_features[feature.id] = feature
                propagate_planes(feature, context)
        elif isinstance(feature, RevolveFeature):
            if feature.sketch_id in context.resolved_planes:
                context.evaluated_features[feature.id] = feature
                propagate_planes(feature, context)
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
                propagate_planes(feature, context)
        elif isinstance(feature, MirrorFeature):
            context.evaluated_features[feature.id] = feature
            propagate_planes(feature, context)
        else:
            # Other feature types can be structural dependencies without
            # producing supported semantic planes.
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


def resolve_axis_reference(reference: Any, context: Any) -> tuple[Vector3, Vector3]:
    """Resolve a Revolve axis from current history state, never mesh topology."""

    datum_axes = {
        "X": (1.0, 0.0, 0.0),
        "Y": (0.0, 1.0, 0.0),
        "Z": (0.0, 0.0, 1.0),
    }
    if reference.reference_type == "DATUM_AXIS":
        if reference.axis not in datum_axes:
            raise PlaneResolutionError(f"Unsupported datum axis: {reference.axis}")
        sign = -1.0 if reference.direction < 0 else 1.0
        frame_matrix = getattr(context, "frame_matrix", IDENTITY_MATRIX)
        origin = transform_point(frame_matrix, (0.0, 0.0, 0.0))
        direction = transform_vector(
            frame_matrix,
            tuple(sign * value for value in datum_axes[reference.axis]),
        )
        return origin, _normalize(direction)

    if reference.reference_type != "SKETCH_LINE":
        raise PlaneResolutionError("Axis is not resolved.")
    from .entities import SketchLine
    from .sketch import SketchFeature, sketch_to_world

    sketch = context.evaluated_features.get(reference.sketch_id)
    if not isinstance(sketch, SketchFeature):
        raise PlaneResolutionError("Axis source Sketch is missing or invalid.")
    line = next(
        (
            entity
            for entity in sketch.entities
            if isinstance(entity, SketchLine) and entity.id == reference.entity_id
        ),
        None,
    )
    if line is None:
        raise PlaneResolutionError("Referenced SketchLine axis is unavailable.")
    start = sketch_to_world(sketch, line.x1, line.y1)
    end = sketch_to_world(sketch, line.x2, line.y2)
    direction = _normalize(tuple(end[index] - start[index] for index in range(3)))
    if reference.direction < 0:
        direction = tuple(-value for value in direction)
    return start, direction


def rotate_plane_about_axis(
    plane: ResolvedPlane,
    axis_origin: Vector3,
    axis_direction: Vector3,
    angle: float,
) -> ResolvedPlane:
    """Rotate a semantic plane rigidly around a resolved Revolve axis."""

    direction = _normalize(axis_direction)

    def rotate_vector(vector: Vector3) -> Vector3:
        cosine, sine = cos(angle), sin(angle)
        parallel = sum(vector[index] * direction[index] for index in range(3))
        cross = _cross(direction, vector)
        return tuple(
            vector[index] * cosine
            + cross[index] * sine
            + direction[index] * parallel * (1.0 - cosine)
            for index in range(3)
        )

    offset = tuple(plane.origin[index] - axis_origin[index] for index in range(3))
    rotated_offset = rotate_vector(offset)
    origin = tuple(axis_origin[index] + rotated_offset[index] for index in range(3))
    return ResolvedPlane(
        origin,
        rotate_vector(plane.x_axis),
        rotate_vector(plane.y_axis),
        rotate_vector(plane.normal),
    )


def resolve_revolve_cap_planes(
    feature: Any, context: Any
) -> dict[tuple[str, str | None], ResolvedPlane]:
    """Resolve planar faces generated by Revolve without reading mesh topology.

    Partial sweeps have two boundary planes.  A full sweep has no boundary
    planes, but a profile edge perpendicular to the axis generates a genuine
    planar annulus/disk (for example the top or bottom of a cylinder/cone).
    Those planes are keyed by the persistent source SketchLine UUID.
    """

    source_plane = context.resolved_planes.get(feature.sketch_id)
    if source_plane is None:
        raise PlaneResolutionError("Source sketch plane is not resolved.")
    axis_origin, axis_direction = resolve_axis_reference(
        feature.axis_reference, context
    )
    if abs(abs(feature.angle) - tau) > 1e-9:
        return {
            ("START_CAP", None): source_plane,
            ("END_CAP", None): rotate_plane_about_axis(
                source_plane, axis_origin, axis_direction, feature.angle
            ),
        }

    from .entities import SketchLine
    from .profile import ProfileDetector
    from .sketch import SketchFeature, sketch_to_world

    source = context.evaluated_features.get(feature.sketch_id)
    if not isinstance(source, SketchFeature):
        return {}
    detected = ProfileDetector().detect(source)
    if not detected.success or detected.profile is None:
        return {}
    profile_entity_ids = {
        entity_id
        for loop in detected.profile.iter_loops()
        for entity_id in loop.entity_ids
        if entity_id
    }
    axis_tolerance = 1e-7
    candidates: list[tuple[str, ResolvedPlane]] = []
    for entity in source.entities:
        if (
            not isinstance(entity, SketchLine)
            or entity.construction
            or entity.id not in profile_entity_ids
        ):
            continue
        start = sketch_to_world(source, entity.x1, entity.y1)
        end = sketch_to_world(source, entity.x2, entity.y2)
        edge = tuple(end[index] - start[index] for index in range(3))
        try:
            x_axis = _normalize(edge)
        except PlaneResolutionError:
            continue
        if abs(sum(x_axis[index] * axis_direction[index] for index in range(3))) > axis_tolerance:
            continue
        start_axial = sum(
            (start[index] - axis_origin[index]) * axis_direction[index]
            for index in range(3)
        )
        end_axial = sum(
            (end[index] - axis_origin[index]) * axis_direction[index]
            for index in range(3)
        )
        if abs(start_axial - end_axial) > axis_tolerance:
            continue
        radial_start = tuple(
            start[index] - axis_origin[index] - start_axial * axis_direction[index]
            for index in range(3)
        )
        radial_end = tuple(
            end[index] - axis_origin[index] - end_axial * axis_direction[index]
            for index in range(3)
        )
        if max(
            sqrt(sum(value * value for value in radial_start)),
            sqrt(sum(value * value for value in radial_end)),
        ) <= axis_tolerance:
            continue
        y_axis = _normalize(_cross(axis_direction, x_axis))
        candidates.append((entity.id, ResolvedPlane(start, x_axis, y_axis, axis_direction)))

    candidates.sort(key=lambda item: item[0])
    roles = ("START_CAP", "END_CAP")
    return {
        (roles[index], entity_id): plane
        for index, (entity_id, plane) in enumerate(candidates[: len(roles)])
    }


def _transform_plane(plane: ResolvedPlane, matrix: Matrix4) -> ResolvedPlane:
    """Apply a rigid history transform to a resolved semantic plane."""

    return ResolvedPlane(
        transform_point(matrix, plane.origin),
        transform_vector(matrix, plane.x_axis),
        transform_vector(matrix, plane.y_axis),
        transform_vector(matrix, plane.normal),
    )
