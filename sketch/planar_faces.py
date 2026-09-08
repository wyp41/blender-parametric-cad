"""Runtime semantic plane propagation and topology-independent face matching."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from .plane import (
    PlaneReference,
    PlaneResolver,
    PlaneResolutionError,
    ResolvedPlane,
    _transform_plane,
    resolve_revolve_cap_planes,
)
from .entities import SketchLine
from ..core.references import FaceReference


@dataclass(frozen=True)
class PlaneMatchTolerance:
    normal: float = 1e-6
    distance: float = 1e-7
    relative_distance: float = 1e-8


@dataclass(frozen=True)
class FaceCandidate:
    polygon_index: int
    planar: bool
    semantic_face: FaceReference | None = None
    semantic_plane: PlaneReference | None = None


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


class PlanarFaceResolver:
    def __init__(self, tolerance=PlaneMatchTolerance()):
        self.tolerance = tolerance

    def candidate(self, polygon_index, evaluation_context):
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
        return FaceCandidate(polygon_index, True)

    def resolve_polygon(self, polygon_index, evaluation_context):
        return self.candidate(polygon_index, evaluation_context).semantic_plane

    def build_cache(self, evaluation_context):
        return {p.index: self.candidate(p.index, evaluation_context)
                for p in evaluation_context.current_body.polygons}
