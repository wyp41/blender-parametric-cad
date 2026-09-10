"""Persistent straight-edge identity and runtime edge candidate resolution."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Any

from ..core.references import EdgeReference, EdgeSignature
from ..core.transform import IDENTITY_MATRIX, Matrix4
from .plane import PlaneReference, resolve_axis_reference
from .planar_faces import PlaneMatchTolerance, PlanarFaceResolver
from .entities import SketchLine
from .sketch import SketchFeature, sketch_to_world


@dataclass(frozen=True)
class EdgeMatchTolerance:
    """Centralized tolerances used by persistent edge matching."""

    direction: float = 1e-6
    line_distance: float = 1e-7
    relative_line_distance: float = 1e-6
    midpoint: float = 1e-6
    relative_midpoint: float = 1e-5
    length: float = 1e-7
    relative_length: float = 1e-5
    endpoint: float = 1e-6
    relative_endpoint: float = 1e-5
    revolve_angle: float = 1e-9
    minimum_length: float = 1e-12


@dataclass(frozen=True)
class ResolvedEdge:
    """Disposable geometry passed from the resolver to a geometry backend."""

    mesh_edge_index: int
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    midpoint: tuple[float, float, float]
    direction: tuple[float, float, float]
    length: float
    adjacent_face_indices: tuple[int, ...]


@dataclass(frozen=True)
class EdgeCandidate:
    """Runtime-only edge candidate for the current evaluated mesh."""

    mesh_edge_index: int
    semantic_reference: EdgeReference | None
    adjacent_faces: tuple[int, ...]
    local_signature: EdgeSignature | None
    resolved_edge: ResolvedEdge
    resolution_error: str | None = None

    @property
    def start(self):
        return self.resolved_edge.start

    @property
    def end(self):
        return self.resolved_edge.end

    @property
    def midpoint(self):
        return self.resolved_edge.midpoint

    @property
    def direction(self):
        return self.resolved_edge.direction

    @property
    def length(self):
        return self.resolved_edge.length


class EdgeResolutionError(ValueError):
    """A persistent edge is missing, ambiguous, or unsupported."""

    def __init__(self, message: str, status: str = "MISSING") -> None:
        super().__init__(message)
        self.status = status


class PersistentEdgeResolver:
    """Resolve persistent edge references without using topology indices."""

    def __init__(
        self,
        tolerance: EdgeMatchTolerance = EdgeMatchTolerance(),
        plane_tolerance: PlaneMatchTolerance = PlaneMatchTolerance(),
    ) -> None:
        self.tolerance = tolerance
        self.plane_resolver = PlanarFaceResolver(plane_tolerance)

    def build_cache(self, evaluation_context: Any) -> dict[int, EdgeCandidate]:
        mesh = getattr(evaluation_context, "current_body", None)
        if mesh is None or not hasattr(mesh, "vertices") or not hasattr(mesh, "polygons"):
            return {}

        try:
            face_candidates = self.plane_resolver.build_cache(evaluation_context)
        except (AttributeError, IndexError, TypeError, ValueError):
            face_candidates = {}

        frame_matrix = getattr(evaluation_context, "frame_matrix", IDENTITY_MATRIX)
        edge_records = _mesh_edge_records(mesh)
        producer = _body_producer_id(evaluation_context)
        cache: dict[int, EdgeCandidate] = {}
        for edge_index, vertex_indices, adjacent_faces in edge_records:
            geometry = _resolved_edge(
                mesh,
                edge_index,
                vertex_indices,
                adjacent_faces,
                frame_matrix,
                self.tolerance.minimum_length,
            )
            if geometry is None:
                continue
            signature = _edge_signature(geometry, frame_matrix)
            planes = _adjacent_planes(face_candidates, adjacent_faces)
            semantic_reference = None
            resolution_error = None
            if not planes:
                resolution_error = (
                    "This edge is not bounded by a supported persistent planar face."
                )
            elif len(planes) == 2 and planes[0] == planes[1]:
                resolution_error = (
                    "This edge is only a tessellation boundary inside one planar face."
                )
            elif len(planes) == 1 and _is_full_revolve_cap_boundary(
                planes[0], evaluation_context, self.tolerance
            ):
                resolution_error = (
                    "Curved Revolve boundaries are not supported as persistent straight edges."
                )
            else:
                boundary_source_ids = _straight_boundary_source_ids(
                    planes, geometry, evaluation_context, self.tolerance
                )
                if len(planes) == 1 and not boundary_source_ids:
                    resolution_error = (
                        "Only straight edges bounded by two known planes, or a supported "
                        "Revolve SketchLine cap boundary, can be persistent."
                    )
                elif producer:
                    source_ids = tuple(
                        dict.fromkeys(
                            (
                                *(
                                    reference.source_entity_id
                                    for reference in planes
                                    if getattr(reference, "source_entity_id", None)
                                ),
                                *boundary_source_ids,
                            )
                        )
                    )
                    semantic_reference = EdgeReference(
                        producer_feature_id=producer,
                        role=("PLANAR_INTERSECTION" if len(planes) == 2 else "PLANAR_BOUNDARY"),
                        adjacent_plane_refs=tuple(planes[:2]) + (None,) * (2 - len(planes)),
                        source_entity_ids=source_ids,
                        local_signature=signature,
                    )
                else:
                    resolution_error = "This body has no persistent producer feature."
            cache[edge_index] = EdgeCandidate(
                mesh_edge_index=edge_index,
                semantic_reference=semantic_reference,
                adjacent_faces=adjacent_faces,
                local_signature=signature,
                resolved_edge=geometry,
                resolution_error=resolution_error,
            )
        return cache

    def resolve(self, reference: EdgeReference, evaluation_context: Any) -> ResolvedEdge:
        candidates = _ensure_cache(evaluation_context, self)
        if not candidates:
            raise EdgeResolutionError(
                "Persistent edge reference is missing after rebuild.", "MISSING"
            )
        supported = [
            candidate
            for candidate in candidates.values()
            if candidate.semantic_reference is not None
        ]

        exact = [
            candidate
            for candidate in supported
            if getattr(evaluation_context, "edge_provenance", {}).get(
                candidate.mesh_edge_index
            ) == reference
        ]
        if len(exact) == 1:
            return exact[0].resolved_edge
        if len(exact) > 1:
            raise EdgeResolutionError(
                "Persistent edge reference is ambiguous after rebuild.", "AMBIGUOUS"
            )

        semantic = [
            candidate
            for candidate in supported
            if _adjacent_plane_identity_matches(
                reference,
                candidate.semantic_reference,
                self.plane_resolver.tolerance,
            )
        ]
        if semantic:
            if len(semantic) == 1:
                return semantic[0].resolved_edge
            narrowed = [
                candidate
                for candidate in semantic
                if _signature_matches(reference.local_signature, candidate.local_signature, self.tolerance)
            ]
            if len(narrowed) == 1:
                return narrowed[0].resolved_edge
            raise EdgeResolutionError(
                "Persistent edge reference is ambiguous after rebuild.", "AMBIGUOUS"
            )

        # A derived signature is a fallback for references that have no
        # semantic adjacent-plane identity.  Once an edge carries planes, a
        # signature-only match could silently jump to a different edge whose
        # topology merely happens to look similar.
        if not any(item is not None for item in reference.adjacent_plane_refs):
            signature_matches = [
                candidate
                for candidate in supported
                if candidate.semantic_reference is not None
                and candidate.semantic_reference.producer_feature_id
                == reference.producer_feature_id
                and _signature_matches(
                    reference.local_signature, candidate.local_signature, self.tolerance
                )
            ]
            if len(signature_matches) == 1:
                return signature_matches[0].resolved_edge
            if len(signature_matches) > 1:
                raise EdgeResolutionError(
                    "Persistent edge reference is ambiguous after rebuild.", "AMBIGUOUS"
                )
        raise EdgeResolutionError(
            "Persistent edge reference is missing after rebuild.", "MISSING"
        )

    def resolve_all(
        self, references: list[EdgeReference] | tuple[EdgeReference, ...], evaluation_context: Any
    ) -> list[ResolvedEdge]:
        return [self.resolve(reference, evaluation_context) for reference in references]


def publish_edge_candidates(
    evaluation_context: Any,
    producer_feature_id: str,
    resolver: PersistentEdgeResolver | None = None,
) -> dict[int, EdgeCandidate]:
    """Populate the disposable edge cache after a body-producing feature."""

    resolver = resolver or PersistentEdgeResolver()
    cache = resolver.build_cache(evaluation_context)
    evaluation_context.edge_candidates = cache
    evaluation_context.edge_provenance = {
        index: candidate.semantic_reference
        for index, candidate in cache.items()
        if candidate.semantic_reference is not None
    }
    evaluation_context.edge_producer_feature_id = producer_feature_id
    evaluation_context.edge_candidates_ready = True
    return cache


def ensure_edge_candidates(
    evaluation_context: Any, resolver: PersistentEdgeResolver | None = None
) -> dict[int, EdgeCandidate]:
    if getattr(evaluation_context, "edge_candidates_ready", False):
        return getattr(evaluation_context, "edge_candidates", {})
    producer = _body_producer_id(evaluation_context)
    if producer:
        return publish_edge_candidates(evaluation_context, producer, resolver)
    return {}


def _ensure_cache(context: Any, resolver: PersistentEdgeResolver) -> dict[int, EdgeCandidate]:
    cache = ensure_edge_candidates(context, resolver)
    return cache


def _body_producer_id(context: Any) -> str | None:
    producer = getattr(context, "edge_producer_feature_id", None)
    if producer:
        return str(producer)
    producer = getattr(context, "body_producer_feature_id", None)
    if producer:
        return str(producer)
    producer = getattr(context, "derived_producer_feature_id", None)
    if producer:
        return str(producer)
    for feature in reversed(tuple(getattr(context, "evaluated_features", {}).values())):
        if getattr(feature, "feature_type", None) in {
            "EXTRUDE", "REVOLVE", "TRANSFORM", "MIRROR", "CHAMFER", "FILLET"
        }:
            return str(feature.id)
    return None


def _mesh_edge_records(mesh: Any):
    face_map: dict[tuple[int, int], list[int]] = {}
    for face_index, polygon in enumerate(getattr(mesh, "polygons", ())):
        vertices = tuple(int(index) for index in polygon.vertices)
        for index, vertex_index in enumerate(vertices):
            key = tuple(sorted((vertex_index, vertices[(index + 1) % len(vertices)])))
            face_map.setdefault(key, []).append(face_index)

    records = []
    mesh_edges = getattr(mesh, "edges", None)
    if mesh_edges is not None and len(mesh_edges):
        for edge_index, edge in enumerate(mesh_edges):
            vertices = tuple(int(index) for index in edge.vertices)
            if len(vertices) != 2:
                continue
            key = tuple(sorted(vertices))
            records.append((edge_index, vertices, tuple(face_map.get(key, ()))))
        return records

    for edge_index, (key, faces) in enumerate(face_map.items()):
        records.append((edge_index, key, tuple(faces)))
    return records


def _resolved_edge(
    mesh: Any,
    edge_index: int,
    vertex_indices: tuple[int, int],
    adjacent_faces: tuple[int, ...],
    frame_matrix: Matrix4,
    minimum_length: float,
) -> ResolvedEdge | None:
    try:
        start = tuple(float(value) for value in mesh.vertices[vertex_indices[0]].co)
        end = tuple(float(value) for value in mesh.vertices[vertex_indices[1]].co)
    except (AttributeError, IndexError, TypeError, ValueError):
        return None
    delta = tuple(end[index] - start[index] for index in range(3))
    length = _length(delta)
    if length <= minimum_length:
        return None
    direction = tuple(value / length for value in delta)
    midpoint = tuple((start[index] + end[index]) * 0.5 for index in range(3))
    return ResolvedEdge(edge_index, start, end, midpoint, direction, length, adjacent_faces)


def _edge_signature(edge: ResolvedEdge, frame_matrix: Matrix4) -> EdgeSignature:
    start = _inverse_point(frame_matrix, edge.start)
    end = _inverse_point(frame_matrix, edge.end)
    midpoint = tuple((start[index] + end[index]) * 0.5 for index in range(3))
    direction = _normalize(tuple(end[index] - start[index] for index in range(3)))
    line_offset = tuple(
        midpoint[index] - sum(midpoint[item] * direction[item] for item in range(3)) * direction[index]
        for index in range(3)
    )
    return EdgeSignature(direction, line_offset, midpoint, _length(tuple(end[i] - start[i] for i in range(3))))


def _adjacent_planes(face_candidates: dict[int, Any], adjacent_faces: tuple[int, ...]):
    values: list[PlaneReference] = []
    for face_index in adjacent_faces:
        candidate = face_candidates.get(face_index)
        reference = getattr(candidate, "semantic_plane", None)
        if reference is None or reference in values:
            continue
        values.append(reference)
    values.sort(key=_plane_sort_key)
    return tuple(values[:2])


def _plane_sort_key(reference: PlaneReference):
    return (
        str(getattr(reference, "reference_type", "")),
        str(getattr(reference, "feature_id", "") or ""),
        str(getattr(reference, "role", "") or ""),
        str(getattr(reference, "source_entity_id", "") or ""),
        tuple(getattr(reference, "local_normal", ()) or ()),
        float(getattr(reference, "local_offset", 0.0) or 0.0),
    )


def _adjacent_plane_identity_matches(
    reference: EdgeReference,
    candidate: EdgeReference | None,
    tolerance: PlaneMatchTolerance,
) -> bool:
    if candidate is None:
        return False
    expected = tuple(item for item in reference.adjacent_plane_refs if item is not None)
    actual = tuple(item for item in candidate.adjacent_plane_refs if item is not None)
    # A reference may intentionally persist only one adjacent plane (for
    # example a supported Revolve cap boundary).  A candidate must contain at
    # least those planes, but may expose an additional known planar neighbor;
    # the signature then disambiguates the candidates if necessary.
    if not expected or not actual or len(actual) < len(expected):
        return False
    if not all(
        any(_plane_identity_equal(item, other, tolerance) for other in actual)
        for item in expected
    ):
        return False
    return all(source_id in candidate.source_entity_ids for source_id in reference.source_entity_ids)


def _plane_identity_equal(
    first: Any, second: Any, tolerance: PlaneMatchTolerance
) -> bool:
    if first is second:
        return True
    if first is None or second is None:
        return False
    if getattr(first, "reference_type", None) != getattr(second, "reference_type", None):
        return False
    if getattr(first, "reference_type", None) == "DERIVED_PLANE":
        return (
            getattr(first, "producer_feature_id", None)
            == getattr(second, "producer_feature_id", None)
            and tuple(getattr(first, "source_feature_ids", ()))
            == tuple(getattr(second, "source_feature_ids", ()))
            and abs(
                float(getattr(first, "local_offset", 0.0))
                - float(getattr(second, "local_offset", 0.0))
            )
            <= tolerance.distance
            + max(
                abs(float(getattr(first, "local_offset", 0.0))),
                abs(float(getattr(second, "local_offset", 0.0))),
                1e-12,
            )
            * tolerance.relative_distance
            and abs(
                sum(
                    float(a) * float(b)
                    for a, b in zip(
                        getattr(first, "local_normal", ()) or (),
                        getattr(second, "local_normal", ()) or (),
                    )
                )
            )
            >= 1.0 - tolerance.normal
        )
    return (
        getattr(first, "feature_id", None) == getattr(second, "feature_id", None)
        and getattr(first, "role", None) == getattr(second, "role", None)
        and getattr(first, "source_entity_id", None)
        == getattr(second, "source_entity_id", None)
    )


def _signature_matches(
    expected: EdgeSignature | None,
    actual: EdgeSignature | None,
    tolerance: EdgeMatchTolerance,
) -> bool:
    if expected is None or actual is None:
        return False
    direction_dot = abs(sum(expected.local_direction[i] * actual.local_direction[i] for i in range(3)))
    if direction_dot < 1.0 - tolerance.direction:
        return False
    line_scale = max(_length(expected.local_line_offset), _length(actual.local_line_offset), 1e-12)
    if _length(_subtract(expected.local_line_offset, actual.local_line_offset)) > (
        tolerance.line_distance + line_scale * tolerance.relative_line_distance
    ):
        return False
    length_scale = max(expected.length_hint, actual.length_hint, 1e-12)
    if abs(expected.length_hint - actual.length_hint) > (
        tolerance.length + length_scale * tolerance.relative_length
    ):
        return False
    midpoint_scale = max(expected.length_hint, actual.length_hint, 1e-6)
    return _length(_subtract(expected.midpoint_hint, actual.midpoint_hint)) <= (
        tolerance.midpoint + midpoint_scale * tolerance.relative_midpoint
    )


def _straight_boundary_source_ids(
    planes: tuple[PlaneReference, ...],
    edge: ResolvedEdge,
    context: Any,
    tolerance: EdgeMatchTolerance,
) -> tuple[str, ...]:
    """Identify a straight SketchLine on a partial Revolve cap.

    A single cap plane is not enough to make a mesh segment persistent: a
    tessellated circular boundary would otherwise look like many straight
    edges.  Only a segment whose endpoints match a persistent source
    SketchLine is admitted in that case.
    """

    if len(planes) != 1 or getattr(planes[0], "role", None) not in {"START_CAP", "END_CAP"}:
        return ()
    feature = getattr(context, "evaluated_features", {}).get(
        getattr(planes[0], "feature_id", None)
    )
    if getattr(feature, "feature_type", None) != "REVOLVE":
        return ()
    from math import tau

    if abs(abs(float(getattr(feature, "angle", 0.0))) - tau) <= tolerance.revolve_angle:
        return ()
    source = getattr(context, "evaluated_features", {}).get(
        getattr(feature, "sketch_id", None)
    )
    if not isinstance(source, SketchFeature):
        return ()
    transformed_endpoints = (edge.start, edge.end)
    end_axis = None
    if getattr(planes[0], "role", None) == "END_CAP":
        try:
            end_axis = resolve_axis_reference(feature.axis_reference, context)
        except (AttributeError, TypeError, ValueError):
            return ()
    for entity in source.entities:
        if not isinstance(entity, SketchLine) or entity.construction:
            continue
        first = sketch_to_world(source, entity.x1, entity.y1)
        second = sketch_to_world(source, entity.x2, entity.y2)
        if end_axis is not None:
            first = _rotate_point(first, end_axis[0], end_axis[1], feature.angle)
            second = _rotate_point(second, end_axis[0], end_axis[1], feature.angle)
        if _same_segment(transformed_endpoints, (first, second), tolerance):
            return (entity.id,)
    return ()


def _same_segment(first, second, tolerance: EdgeMatchTolerance) -> bool:
    endpoint_tolerance = tolerance.endpoint + max(
        _length(_subtract(first[0], first[1])),
        _length(_subtract(second[0], second[1])),
        tolerance.minimum_length,
    ) * tolerance.relative_endpoint
    return (
        _length(_subtract(first[0], second[0])) <= endpoint_tolerance
        and _length(_subtract(first[1], second[1])) <= endpoint_tolerance
    ) or (
        _length(_subtract(first[0], second[1])) <= endpoint_tolerance
        and _length(_subtract(first[1], second[0])) <= endpoint_tolerance
    )


def _rotate_point(point, origin, direction, angle):
    direction = _normalize(direction)
    vector = tuple(point[index] - origin[index] for index in range(3))
    from math import cos, sin

    cosine, sine = cos(angle), sin(angle)
    parallel = sum(vector[index] * direction[index] for index in range(3))
    cross = (
        direction[1] * vector[2] - direction[2] * vector[1],
        direction[2] * vector[0] - direction[0] * vector[2],
        direction[0] * vector[1] - direction[1] * vector[0],
    )
    rotated = tuple(
        vector[index] * cosine
        + cross[index] * sine
        + direction[index] * parallel * (1.0 - cosine)
        for index in range(3)
    )
    return tuple(origin[index] + rotated[index] for index in range(3))


def _is_full_revolve_cap_boundary(
    reference: PlaneReference, context: Any, tolerance: EdgeMatchTolerance
) -> bool:
    if getattr(reference, "role", None) not in {"START_CAP", "END_CAP"}:
        return False
    feature = getattr(context, "evaluated_features", {}).get(
        getattr(reference, "feature_id", None)
    )
    if getattr(feature, "feature_type", None) != "REVOLVE":
        return False
    from math import tau

    return abs(abs(float(getattr(feature, "angle", 0.0))) - tau) <= tolerance.revolve_angle


def _inverse_point(matrix: Matrix4, point):
    translated = tuple(point[index] - matrix[index][3] for index in range(3))
    return tuple(
        sum(matrix[row][index] * translated[row] for row in range(3))
        for index in range(3)
    )


def _normalize(vector):
    length = _length(vector)
    if length <= 1e-12:
        raise ValueError("Edge direction has zero length.")
    direction = tuple(value / length for value in vector)
    for value in direction:
        if abs(value) <= 1e-12:
            continue
        if value < 0.0:
            direction = tuple(-component for component in direction)
        break
    return direction


def _subtract(first, second):
    return tuple(first[index] - second[index] for index in range(3))


def _length(vector):
    return sqrt(sum(value * value for value in vector))
