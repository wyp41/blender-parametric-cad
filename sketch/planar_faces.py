"""Runtime semantic plane propagation and topology-independent face matching."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import sqrt
from typing import Any

from .plane import (
    DerivedPlaneReference,
    PlaneReference,
    PlaneResolver,
    RegionHint,
    ResolvedPlane,
    _transform_plane,
    canonical_plane,
    resolve_revolve_cap_planes,
)
from .entities import SketchLine
from ..core.references import FaceReference
from ..core.transform import IDENTITY_MATRIX, Matrix4, transform_point, transform_vector


@dataclass(frozen=True)
class PlaneMatchTolerance:
    normal: float = 1e-6
    distance: float = 1e-7
    relative_distance: float = 1e-8
    centroid: float = 1e-6
    relative_centroid: float = 1e-5
    relative_area: float = 1e-5


@dataclass(frozen=True)
class DerivedPlaneCandidate:
    """Runtime description of one connected planar Boolean region.

    ``polygon_indices`` is deliberately runtime-only.  It is never copied into
    ``DerivedPlaneReference`` or serialized with the CAD document.
    """

    producer_feature_id: str
    local_normal: tuple[float, float, float]
    local_offset: float
    source_feature_ids: tuple[str, ...]
    region_hint: RegionHint
    plane: ResolvedPlane
    polygon_indices: tuple[int, ...]

    def to_reference(self) -> DerivedPlaneReference:
        return DerivedPlaneReference(
            producer_feature_id=self.producer_feature_id,
            local_normal=self.local_normal,
            local_offset=self.local_offset,
            source_feature_ids=self.source_feature_ids,
            region_hint=self.region_hint,
        )


@dataclass(frozen=True)
class FaceCandidate:
    polygon_index: int
    planar: bool
    semantic_face: FaceReference | None = None
    semantic_plane: PlaneReference | None = None
    resolution_error: str | None = None
    derived_candidate: DerivedPlaneCandidate | None = None


@dataclass(frozen=True)
class _PolygonGeometry:
    index: int
    points: tuple[tuple[float, float, float], ...]
    local_points: tuple[tuple[float, float, float], ...]
    normal: tuple[float, float, float]
    local_normal: tuple[float, float, float]
    local_offset: float
    local_centroid: tuple[float, float, float]
    area: float
    scale: float


def propagate_planes(feature, context):
    """Called only after successful evaluation, in history order."""
    from ..features.extrude import ExtrudeFeature
    from ..features.revolve import RevolveFeature
    from ..features.transform import TransformFeature
    from ..features.mirror import MirrorFeature

    planes = context.semantic_planes
    resolver = PlaneResolver()
    if isinstance(feature, ExtrudeFeature):
        source = context.evaluated_features[feature.sketch_id]
        roles = [("START_FACE", None), ("END_FACE", None), ("END_PLANE", None)]
        if feature.depth_mode == "THROUGH_ALL":
            roles = []  # Tool end caps depend on bounds, not on distance.
        roles += [("SIDE_FACE", e.id) for e in source.entities
                  if isinstance(e, SketchLine) and not e.construction
                  and (e.x2 != e.x1 or e.y2 != e.y1)]
        for role, entity_id in roles:
            reference = PlaneReference("FEATURE_PLANE" if role == "END_PLANE" else "FACE",
                                       None, feature.id, role, entity_id)
            planes[(feature.id, role, entity_id)] = resolver.resolve(reference, context)
    elif isinstance(feature, RevolveFeature):
        for key in list(planes):
            if key[0] == feature.id:
                del planes[key]
        for (role, entity_id), plane in resolve_revolve_cap_planes(
            feature, context
        ).items():
            planes[(feature.id, role, entity_id)] = plane
    elif isinstance(feature, TransformFeature):
        matrix = feature.as_transform().matrix
        for key, plane in list(planes.items()):
            planes[key] = _transform_plane(plane, matrix)
        _transform_derived_candidates(context, matrix)
    elif isinstance(feature, MirrorFeature):
        mirror = resolver.resolve(feature.mirror_plane, context)

        def reflect(vector):
            dot = sum(vector[i] * mirror.normal[i] for i in range(3))
            return tuple(vector[i] - 2 * dot * mirror.normal[i] for i in range(3))

        for (producer, role, entity_id), plane in list(planes.items()):
            if producer != feature.source_feature_id:
                continue
            delta = reflect(tuple(plane.origin[i] - mirror.origin[i] for i in range(3)))
            origin = tuple(mirror.origin[i] + delta[i] for i in range(3))
            x = reflect(plane.x_axis)
            y = tuple(-v for v in reflect(plane.y_axis))
            planes[(feature.id, role, entity_id)] = ResolvedPlane(origin, x, y, reflect(plane.normal))


def publish_derived_candidates(
    evaluation_context: Any,
    producer_feature_id: str,
    source_feature_ids: tuple[str, ...] | list[str] = (),
    tolerance: PlaneMatchTolerance = PlaneMatchTolerance(),
) -> None:
    """Build the disposable candidate cache for a Boolean result mesh."""

    candidates = _extract_derived_candidates(
        evaluation_context.current_body,
        producer_feature_id,
        evaluation_context.semantic_planes,
        getattr(evaluation_context, "frame_matrix", IDENTITY_MATRIX),
        tuple(dict.fromkeys(str(value) for value in source_feature_ids if value)),
        tolerance,
    )
    evaluation_context.derived_plane_candidates = {
        producer_feature_id: tuple(candidates)
    }
    evaluation_context.derived_polygon_candidates = {
        polygon_index: candidate
        for candidate in candidates
        for polygon_index in candidate.polygon_indices
    }
    evaluation_context.derived_producer_feature_id = producer_feature_id
    evaluation_context.derived_candidates_ready = True


def ensure_derived_candidates(
    evaluation_context: Any,
    tolerance: PlaneMatchTolerance = PlaneMatchTolerance(),
) -> None:
    """Hydrate a manually-created evaluation context when it has a producer."""

    if getattr(evaluation_context, "derived_candidates_ready", False):
        return
    producer = getattr(evaluation_context, "derived_producer_feature_id", None)
    if producer:
        publish_derived_candidates(evaluation_context, producer, (), tolerance)


def match_derived_reference(
    reference: PlaneReference,
    candidates: tuple[DerivedPlaneCandidate, ...] | list[DerivedPlaneCandidate],
    tolerance: PlaneMatchTolerance = PlaneMatchTolerance(),
) -> DerivedPlaneCandidate | None:
    """Return a unique candidate, or ``None`` for missing/ambiguous matches."""

    matches = _plane_matches(reference, candidates, tolerance)
    if len(matches) == 1:
        return matches[0]
    if len(matches) <= 1:
        return None

    hint = reference.region_hint
    if hint is None:
        return None
    hinted = [candidate for candidate in matches if _region_matches(hint, candidate.region_hint, tolerance)]
    return hinted[0] if len(hinted) == 1 else None


def derived_reference_status(
    reference: PlaneReference,
    candidates: tuple[DerivedPlaneCandidate, ...] | list[DerivedPlaneCandidate],
    tolerance: PlaneMatchTolerance = PlaneMatchTolerance(),
) -> tuple[DerivedPlaneCandidate | None, str]:
    """Return ``(candidate, status)`` with status ``OK``, ``MISSING`` or ``AMBIGUOUS``."""

    matches = _plane_matches(reference, candidates, tolerance)
    if len(matches) == 1:
        return matches[0], "OK"
    if not matches:
        return None, "MISSING"
    hint = reference.region_hint
    if hint is not None:
        hinted = [candidate for candidate in matches if _region_matches(hint, candidate.region_hint, tolerance)]
        if len(hinted) == 1:
            return hinted[0], "OK"
    return None, "AMBIGUOUS"


def _plane_matches(
    reference: PlaneReference,
    candidates: tuple[DerivedPlaneCandidate, ...] | list[DerivedPlaneCandidate],
    tolerance: PlaneMatchTolerance,
) -> list[DerivedPlaneCandidate]:
    if reference.local_normal is None or reference.local_offset is None:
        return []
    matches: list[DerivedPlaneCandidate] = []
    for candidate in candidates:
        dot = abs(sum(reference.local_normal[i] * candidate.local_normal[i] for i in range(3)))
        if abs(dot - 1.0) > tolerance.normal:
            continue
        distance = tolerance.distance + max(
            abs(reference.local_offset), abs(candidate.local_offset), 1e-12
        ) * tolerance.relative_distance
        if abs(reference.local_offset - candidate.local_offset) <= distance:
            matches.append(candidate)
    return matches


def _region_matches(
    expected: RegionHint, actual: RegionHint, tolerance: PlaneMatchTolerance
) -> bool:
    centroid_distance = sqrt(
        sum((expected.centroid[i] - actual.centroid[i]) ** 2 for i in range(3))
    )
    centroid_scale = max(sqrt(max(expected.area, actual.area, 0.0)), 1e-6)
    centroid_tolerance = tolerance.centroid + centroid_scale * tolerance.relative_centroid
    area_tolerance = max(expected.area, actual.area, 1e-12) * tolerance.relative_area
    return (
        centroid_distance <= centroid_tolerance
        and abs(expected.area - actual.area) <= area_tolerance
    )


def _transform_derived_candidates(context: Any, matrix: Matrix4) -> None:
    candidates_by_producer = getattr(context, "derived_plane_candidates", {})
    if not candidates_by_producer:
        return
    updated: dict[str, tuple[DerivedPlaneCandidate, ...]] = {}
    for producer, candidates in candidates_by_producer.items():
        updated[producer] = tuple(
            replace(candidate, plane=_transform_plane(candidate.plane, matrix))
            for candidate in candidates
        )
    context.derived_plane_candidates = updated
    context.derived_polygon_candidates = {
        polygon_index: candidate
        for candidates in updated.values()
        for candidate in candidates
        for polygon_index in candidate.polygon_indices
    }


def _extract_derived_candidates(
    mesh: Any,
    producer_feature_id: str,
    semantic_planes: dict[tuple, ResolvedPlane],
    frame_matrix: Matrix4,
    source_feature_ids: tuple[str, ...],
    tolerance: PlaneMatchTolerance,
) -> list[DerivedPlaneCandidate]:
    geometries: list[_PolygonGeometry] = []
    for polygon_index, polygon in enumerate(getattr(mesh, "polygons", ())):
        geometry = _polygon_geometry(
            mesh, polygon, polygon_index, frame_matrix, tolerance
        )
        if geometry is not None:
            geometries.append(geometry)
    if not geometries:
        return []

    buckets: list[list[_PolygonGeometry]] = []
    for geometry in geometries:
        bucket = next(
            (
                bucket
                for bucket in buckets
                if _same_local_plane(geometry, bucket[0], tolerance)
            ),
            None,
        )
        if bucket is None:
            buckets.append([geometry])
        else:
            bucket.append(geometry)

    candidates: list[DerivedPlaneCandidate] = []
    for bucket in buckets:
        groups = _connected_groups(bucket)
        for group in groups:
            if _matches_existing_semantic_plane(group, semantic_planes, tolerance):
                continue
            area = sum(item.area for item in group)
            if area <= 1e-18:
                continue
            centroid = tuple(
                sum(item.local_centroid[index] * item.area for item in group) / area
                for index in range(3)
            )
            representative = group[0]
            local_normal, local_offset = canonical_plane(
                representative.local_normal, representative.local_offset
            )
            local_x, local_y = _plane_axes(local_normal)
            world_origin = transform_point(frame_matrix, centroid)
            world_x = _normalize(transform_vector(frame_matrix, local_x))
            world_y = _normalize(transform_vector(frame_matrix, local_y))
            world_normal = _normalize(transform_vector(frame_matrix, local_normal))
            candidates.append(
                DerivedPlaneCandidate(
                    producer_feature_id=producer_feature_id,
                    local_normal=local_normal,
                    local_offset=local_offset,
                    source_feature_ids=tuple(dict.fromkeys(
                        (producer_feature_id, *source_feature_ids)
                    )),
                    region_hint=RegionHint(centroid, area),
                    plane=ResolvedPlane(world_origin, world_x, world_y, world_normal),
                    polygon_indices=tuple(sorted(item.index for item in group)),
                )
            )
    candidates.sort(key=lambda item: (item.local_offset, item.region_hint.centroid, item.polygon_indices))
    return candidates


def _same_local_plane(
    first: _PolygonGeometry,
    second: _PolygonGeometry,
    tolerance: PlaneMatchTolerance,
) -> bool:
    dot = abs(sum(first.local_normal[i] * second.local_normal[i] for i in range(3)))
    if abs(dot - 1.0) > tolerance.normal:
        return False
    distance = tolerance.distance + max(
        first.scale, second.scale, 1e-12
    ) * tolerance.relative_distance
    return abs(first.local_offset - second.local_offset) <= distance


def _polygon_geometry(
    mesh: Any,
    polygon: Any,
    polygon_index: int,
    frame_matrix: Matrix4,
    tolerance: PlaneMatchTolerance,
) -> _PolygonGeometry | None:
    points = tuple(
        tuple(float(value) for value in mesh.vertices[vertex_index].co)
        for vertex_index in polygon.vertices
    )
    if len(points) < 3:
        return None
    normal = tuple(float(value) for value in getattr(polygon, "normal", (0.0, 0.0, 0.0)))
    if _length(normal) <= 1e-12:
        normal = _cross(
            tuple(points[1][i] - points[0][i] for i in range(3)),
            tuple(points[2][i] - points[0][i] for i in range(3)),
        )
    normal = _normalize(normal)
    scale = max(
        sqrt(sum((point[i] - points[0][i]) ** 2 for i in range(3)))
        for point in points
    )
    planarity_tolerance = tolerance.distance + scale * tolerance.relative_distance
    if any(
        abs(sum((point[i] - points[0][i]) * normal[i] for i in range(3)))
        > planarity_tolerance
        for point in points
    ):
        return None
    local_points = tuple(_inverse_point(frame_matrix, point) for point in points)
    local_normal = _normalize(_inverse_vector(frame_matrix, normal))
    local_normal, local_offset = canonical_plane(
        local_normal, sum(local_normal[i] * local_points[0][i] for i in range(3))
    )
    local_centroid = tuple(
        sum(point[index] for point in local_points) / len(local_points)
        for index in range(3)
    )
    area = _polygon_area(local_points)
    return _PolygonGeometry(
        index=polygon_index,
        points=points,
        local_points=local_points,
        normal=normal,
        local_normal=local_normal,
        local_offset=local_offset,
        local_centroid=local_centroid,
        area=area,
        scale=scale,
    )


def _connected_groups(bucket: list[_PolygonGeometry]) -> list[list[_PolygonGeometry]]:
    parent = list(range(len(bucket)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    edges: dict[tuple[Any, Any], int] = {}
    for index, geometry in enumerate(bucket):
        polygon = geometry.local_points
        for point_index, point in enumerate(polygon):
            other = polygon[(point_index + 1) % len(polygon)]
            # Runtime mesh vertex IDs are not part of persistence, but using
            # coordinates here lets fake meshes and evaluated Blender meshes
            # share the same grouping behavior without leaking indices.
            edge = tuple(sorted((_point_key(point), _point_key(other))))
            previous = edges.get(edge)
            if previous is not None:
                union(index, previous)
            else:
                edges[edge] = index
    groups: dict[int, list[_PolygonGeometry]] = {}
    for index, geometry in enumerate(bucket):
        groups.setdefault(find(index), []).append(geometry)
    return list(groups.values())


def _matches_existing_semantic_plane(
    group: list[_PolygonGeometry],
    semantic_planes: dict[tuple, ResolvedPlane],
    tolerance: PlaneMatchTolerance,
) -> bool:
    representative = group[0]
    for plane in semantic_planes.values():
        if abs(abs(sum(representative.normal[i] * plane.normal[i] for i in range(3))) - 1.0) > tolerance.normal:
            continue
        distance = tolerance.distance + representative.scale * tolerance.relative_distance
        if all(
            abs(sum((point[i] - plane.origin[i]) * plane.normal[i] for i in range(3)))
            <= distance
            for item in group
            for point in item.points
        ):
            return True
    return False


def _polygon_area(points: tuple[tuple[float, float, float], ...]) -> float:
    origin = points[0]
    area = 0.0
    for index in range(1, len(points) - 1):
        first = tuple(points[index][item] - origin[item] for item in range(3))
        second = tuple(points[index + 1][item] - origin[item] for item in range(3))
        area += _length(_cross(first, second)) * 0.5
    return area


def _plane_axes(normal: tuple[float, float, float]):
    references = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    reference = min(references, key=lambda axis: abs(_dot(axis, normal)))
    x_axis = _normalize(_cross(reference, normal))
    y_axis = _normalize(_cross(normal, x_axis))
    return x_axis, y_axis


def _inverse_point(matrix: Matrix4, point):
    translated = tuple(point[index] - matrix[index][3] for index in range(3))
    return tuple(
        sum(matrix[row][index] * translated[row] for row in range(3))
        for index in range(3)
    )


def _inverse_vector(matrix: Matrix4, vector):
    return tuple(
        sum(matrix[row][index] * vector[row] for row in range(3))
        for index in range(3)
    )


def _point_key(point):
    return tuple(round(float(value), 9) for value in point)


def _cross(first, second):
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _dot(first, second):
    return sum(first[index] * second[index] for index in range(3))


def _length(vector):
    return sqrt(sum(value * value for value in vector))


def _normalize(vector):
    length = _length(vector)
    if length <= 1e-12:
        return (0.0, 0.0, 0.0)
    return tuple(value / length for value in vector)


class PlanarFaceResolver:
    def __init__(self, tolerance=PlaneMatchTolerance()):
        self.tolerance = tolerance

    def candidate(self, polygon_index, evaluation_context):
        ensure_derived_candidates(evaluation_context, self.tolerance)
        mesh = evaluation_context.current_body
        polygon = mesh.polygons[polygon_index]
        points = [tuple(mesh.vertices[i].co) for i in polygon.vertices]
        normal = tuple(polygon.normal)
        length = sqrt(sum(v * v for v in normal))
        if len(points) < 3 or length == 0:
            return FaceCandidate(polygon_index, False)
        normal = tuple(v / length for v in normal)
        scale = max(sqrt(sum((p[i] - points[0][i]) ** 2 for i in range(3))) for p in points)
        distance = self.tolerance.distance + scale * self.tolerance.relative_distance

        def lies_on(origin, axis):
            return all(abs(sum((p[i] - origin[i]) * axis[i] for i in range(3))) <= distance for p in points)

        if not lies_on(points[0], normal):
            return FaceCandidate(polygon_index, False)
        planes = evaluation_context.semantic_planes
        exact = evaluation_context.face_provenance.get(polygon_index)
        keys = list(planes)
        if exact:
            key = (exact.feature_id, exact.role, exact.source_entity_id)
            if key in planes:
                keys.remove(key)
                keys.insert(0, key)
        for key in keys:
            plane = planes[key]
            if abs(abs(sum(normal[i] * plane.normal[i] for i in range(3))) - 1) > self.tolerance.normal:
                continue
            if not lies_on(plane.origin, plane.normal):
                continue
            producer, role, entity = key
            face = FaceReference(producer, "END_FACE" if role == "END_PLANE" else role, entity)
            # All surviving end polygons share the existing END_PLANE identity.
            support_role = "END_PLANE" if role == "END_FACE" else role
            reference = PlaneReference("FEATURE_PLANE" if support_role == "END_PLANE" else "FACE",
                                       None, producer, support_role, entity)
            return FaceCandidate(polygon_index, True, face, reference)

        derived = getattr(evaluation_context, "derived_polygon_candidates", {}).get(polygon_index)
        if derived is not None:
            reference = derived.to_reference()
            return FaceCandidate(
                polygon_index,
                True,
                semantic_plane=reference,
                derived_candidate=derived,
            )
        return FaceCandidate(polygon_index, True)

    def resolve_polygon(self, polygon_index, evaluation_context):
        return self.candidate(polygon_index, evaluation_context).semantic_plane

    def build_cache(self, evaluation_context):
        ensure_derived_candidates(evaluation_context, self.tolerance)
        return {p.index: self.candidate(p.index, evaluation_context)
                for p in evaluation_context.current_body.polygons}
