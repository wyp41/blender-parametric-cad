"""Tessellated Blender mesh backend for M2 visualization."""

from __future__ import annotations

from math import ceil, cos, pi, sin, sqrt, tau

import bpy

from ..sketch.profile import SketchProfile
from ..sketch.sketch import SketchFeature, sketch_normal, sketch_to_world
from ..core.references import TopoReference
from .backend import GeometryBackend


class BlenderMeshBackend(GeometryBackend):
    """Build a new disposable Blender Mesh for each history evaluation."""

    circle_segments = 64

    def __init__(self) -> None:
        self._face_provenance: dict[int, dict[int, TopoReference]] = {}

    def create_extrusion(
        self,
        sketch: SketchFeature,
        profile: SketchProfile,
        distance: float,
        direction: int,
    ) -> bpy.types.Mesh:
        return self._create_prism(
            sketch,
            profile,
            0.0,
            distance * direction,
            "CAD_Rebuild_Result",
        )

    def create_extrusion_tool(
        self,
        sketch: SketchFeature,
        profile: SketchProfile,
        body: bpy.types.Mesh,
        direction: int,
    ) -> bpy.types.Mesh:
        normal = sketch_normal(sketch)
        projections = [
            sum(
                (vertex.co[index] - sketch.origin[index]) * normal[index]
                for index in range(3)
            )
            for vertex in body.vertices
        ]
        if not projections:
            raise ValueError("Cannot create a Through All cutter for an empty body.")
        lower, upper = min(projections), max(projections)
        extent = upper - lower
        margin = max(extent * 0.05, 0.001)
        return self._create_prism(
            sketch,
            profile,
            lower - margin,
            upper + margin,
            "CAD_ThroughAll_Cutter",
        )

    def create_blind_extrusion_tool(
        self,
        sketch: SketchFeature,
        profile: SketchProfile,
        distance: float,
        direction: int,
    ) -> bpy.types.Mesh:
        margin = max(distance * 0.01, 1e-6)
        return self._create_prism(
            sketch,
            profile,
            -direction * margin,
            distance * direction,
            "CAD_Blind_Remove_Tool",
        )

    def revolve_profile(
        self,
        sketch: SketchFeature,
        profile: SketchProfile,
        axis_origin: tuple[float, float, float],
        axis_direction: tuple[float, float, float],
        angle: float,
    ) -> bpy.types.Mesh:
        points = self._profile_points(profile)
        normal_length = sqrt(sum(value * value for value in axis_direction))
        if normal_length <= 1e-12:
            raise ValueError("Revolve axis has zero length.")
        direction = tuple(value / normal_length for value in axis_direction)
        base = [sketch_to_world(sketch, u, v) for u, v in points]
        segments = max(8, int(ceil(64.0 * abs(angle) / tau)))
        vertices: list[tuple[float, float, float]] = []
        for ring in range(segments + 1):
            ring_angle = angle * ring / segments
            vertices.extend(
                self._rotate_about_axis(point, axis_origin, direction, ring_angle)
                for point in base
            )

        count = len(base)
        faces = []
        for ring in range(segments):
            next_ring = ring + 1
            for index in range(count):
                next_index = (index + 1) % count
                faces.append(
                    (
                        ring * count + index,
                        ring * count + next_index,
                        next_ring * count + next_index,
                        next_ring * count + index,
                    )
                )
        if abs(angle) < tau - 1e-9:
            faces.append(tuple(reversed(range(count))))
            end = segments * count
            faces.append(tuple(end + index for index in range(count)))

        mesh = bpy.data.meshes.new("CAD_Revolve_Result")
        mesh.from_pydata(vertices, [], faces)
        mesh.validate()
        mesh.update()
        return mesh

    @staticmethod
    def _rotate_about_axis(
        point: tuple[float, float, float],
        origin: tuple[float, float, float],
        direction: tuple[float, float, float],
        angle: float,
    ) -> tuple[float, float, float]:
        vector = tuple(point[index] - origin[index] for index in range(3))
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

    def register_extrude_provenance(
        self, body: bpy.types.Mesh, feature_id: str, profile: SketchProfile
    ) -> None:
        references = {
            0: TopoReference(feature_id, "START_FACE"),
            1: TopoReference(feature_id, "END_FACE"),
        }
        _points, entity_ids = self._profile_points_and_ids(profile)
        for index, entity_id in enumerate(entity_ids):
            if entity_id is not None:
                references[index + 2] = TopoReference(
                    feature_id, "SIDE_FACE", source_entity_id=entity_id
                )
        self._face_provenance[id(body)] = references

    def face_provenance(self, body: bpy.types.Mesh) -> dict[int, TopoReference]:
        return dict(self._face_provenance.get(id(body), {}))

    def boolean_difference(
        self, body: bpy.types.Mesh, tool: bpy.types.Mesh
    ) -> bpy.types.Mesh:
        return self._boolean(body, tool, "DIFFERENCE")

    def boolean_union(self, body: bpy.types.Mesh, tool: bpy.types.Mesh) -> bpy.types.Mesh:
        return self._boolean(body, tool, "UNION")

    def _boolean(
        self, body: bpy.types.Mesh, tool: bpy.types.Mesh, operation: str
    ) -> bpy.types.Mesh:
        internal = self._internal_collection()
        was_hidden = internal.hide_viewport
        internal.hide_viewport = False
        body_object = bpy.data.objects.new("CAD_Boolean_Body", body)
        tool_object = bpy.data.objects.new("CAD_Boolean_Tool", tool)
        internal.objects.link(body_object)
        internal.objects.link(tool_object)
        result: bpy.types.Mesh | None = None
        try:
            modifier = body_object.modifiers.new("CAD_ThroughAll", "BOOLEAN")
            modifier.operation = operation
            modifier.solver = "EXACT"
            modifier.object = tool_object
            depsgraph = bpy.context.evaluated_depsgraph_get()
            depsgraph.update()
            evaluated = body_object.evaluated_get(depsgraph)
            result = bpy.data.meshes.new_from_object(evaluated, depsgraph=depsgraph)
            result.name = "CAD_Rebuild_Result"
            result.validate()
            result.update()
        finally:
            bpy.data.objects.remove(body_object, do_unlink=True)
            bpy.data.objects.remove(tool_object, do_unlink=True)
            internal.hide_viewport = was_hidden
            if tool.users == 0:
                bpy.data.meshes.remove(tool)
        if result is None:
            raise ValueError(f"Blender Boolean {operation.title()} failed.")
        if body.users == 0:
            bpy.data.meshes.remove(body)
        return result

    def _create_prism(
        self,
        sketch: SketchFeature,
        profile: SketchProfile,
        start_offset: float,
        end_offset: float,
        name: str,
    ) -> bpy.types.Mesh:
        if start_offset > end_offset:
            start_offset, end_offset = end_offset, start_offset
        points = self._profile_points(profile)
        normal = sketch_normal(sketch)
        base = [sketch_to_world(sketch, u, v) for u, v in points]
        bottom = [
            tuple(point[index] + normal[index] * start_offset for index in range(3))
            for point in base
        ]
        top = [
            tuple(point[index] + normal[index] * end_offset for index in range(3))
            for point in base
        ]
        count = len(points)
        vertices = bottom + top
        faces = [tuple(reversed(range(count))), tuple(range(count, count * 2))]
        faces.extend(
            (
                index,
                (index + 1) % count,
                (index + 1) % count + count,
                index + count,
            )
            for index in range(count)
        )

        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        return mesh

    @staticmethod
    def _internal_collection() -> bpy.types.Collection:
        scene = bpy.context.scene
        root = bpy.data.collections.get("CAD")
        if root is None:
            root = bpy.data.collections.new("CAD")
            scene.collection.children.link(root)
        elif root.name not in scene.collection.children:
            scene.collection.children.link(root)
        internal = bpy.data.collections.get("INTERNAL")
        if internal is None:
            internal = bpy.data.collections.new("INTERNAL")
            root.children.link(internal)
        elif internal.name not in root.children:
            root.children.link(internal)
        internal.hide_render = True
        return internal

    def _profile_points(self, profile: SketchProfile) -> list[tuple[float, float]]:
        points, _entity_ids = self._profile_points_and_ids(profile)
        return points

    def _profile_points_and_ids(
        self, profile: SketchProfile
    ) -> tuple[list[tuple[float, float]], list[str | None]]:
        if profile.points:
            points = list(profile.points)
            entity_ids: list[str | None] = list(profile.entity_ids)
        elif profile.kind == "CIRCLE" and profile.circle is not None:
            cx, cy, radius = profile.circle
            points = [
                (
                    cx + radius * cos(2.0 * pi * index / self.circle_segments),
                    cy + radius * sin(2.0 * pi * index / self.circle_segments),
                )
                for index in range(self.circle_segments)
            ]
            entity_ids = [None] * len(points)
        else:
            raise ValueError(f"Unsupported profile kind: {profile.kind}")
        if len(entity_ids) != len(points):
            entity_ids = [None] * len(points)
        signed_area = sum(
            points[index][0] * points[(index + 1) % len(points)][1]
            - points[(index + 1) % len(points)][0] * points[index][1]
            for index in range(len(points))
        )
        if signed_area < 0.0:
            return list(reversed(points)), list(reversed(entity_ids))
        return points, entity_ids
