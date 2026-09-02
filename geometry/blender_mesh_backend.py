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
        normal_length = sqrt(sum(value * value for value in axis_direction))
        if normal_length <= 1e-12:
            raise ValueError("Revolve axis has zero length.")
        direction = tuple(value / normal_length for value in axis_direction)
        segments = max(8, int(ceil(64.0 * abs(angle) / tau)))
        full_turn = abs(abs(angle) - tau) <= 1e-9
        vertices: list[tuple[float, float, float]] = []
        faces: list[tuple[int, ...]] = []
        for points, _entity_ids in self._profile_loops_and_ids(profile):
            base = [sketch_to_world(sketch, u, v) for u, v in points]
            offset = len(vertices)
            ring_count = segments if full_turn else segments + 1
            for ring in range(ring_count):
                ring_angle = angle * ring / segments
                vertices.extend(
                    self._rotate_about_axis(point, axis_origin, direction, ring_angle)
                    for point in base
                )

            count = len(base)
            for ring in range(segments):
                next_ring = (ring + 1) % segments if full_turn else ring + 1
                for index in range(count):
                    next_index = (index + 1) % count
                    faces.append(
                        (
                            offset + ring * count + index,
                            offset + ring * count + next_index,
                            offset + next_ring * count + next_index,
                            offset + next_ring * count + index,
                        )
                    )
            if not full_turn:
                faces.append(tuple(offset + index for index in reversed(range(count))))
                end = offset + segments * count
                faces.append(tuple(end + index for index in range(count)))

        # Reversing the axis changes the sweep direction and can invert the
        # generated face winding.  Boolean tools must describe a consistently
        # outward-facing solid, regardless of which axis direction was chosen.
        if self._signed_volume(vertices, faces) < 0.0:
            faces = [tuple(reversed(face)) for face in faces]

        mesh = bpy.data.meshes.new("CAD_Revolve_Result")
        mesh.from_pydata(vertices, [], faces)
        mesh.validate()
        mesh.update()
        return mesh

    @staticmethod
    def _signed_volume(
        vertices: list[tuple[float, float, float]], faces: list[tuple[int, ...]]
    ) -> float:
        volume = 0.0
        for face in faces:
            if len(face) < 3:
                continue
            origin = vertices[face[0]]
            for index in range(1, len(face) - 1):
                first = vertices[face[index]]
                second = vertices[face[index + 1]]
                cross = (
                    first[1] * second[2] - first[2] * second[1],
                    first[2] * second[0] - first[0] * second[2],
                    first[0] * second[1] - first[1] * second[0],
                )
                volume += (
                    origin[0] * cross[0]
                    + origin[1] * cross[1]
                    + origin[2] * cross[2]
                ) / 6.0
        return volume

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
        references: dict[int, TopoReference] = {}
        polygon_index = 0
        for _points, entity_ids in self._profile_loops_and_ids(profile):
            references[polygon_index] = TopoReference(feature_id, "START_FACE")
            references[polygon_index + 1] = TopoReference(feature_id, "END_FACE")
            for index, entity_id in enumerate(entity_ids):
                if entity_id is not None:
                    references[polygon_index + index + 2] = TopoReference(
                        feature_id, "SIDE_FACE", source_entity_id=entity_id
                    )
            polygon_index += len(entity_ids) + 2
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
        # An ADD must produce one real solid.  Blender's Boolean modifier can
        # report success for disjoint inputs while leaving multiple islands in
        # the output; accepting that mesh makes a Part Studio look like one
        # part while it is actually an assembly of disconnected bodies.
        if operation == "UNION":
            try:
                self._validate_union_result(result)
            except Exception:
                if result.users == 0:
                    bpy.data.meshes.remove(result)
                raise
        if body.users == 0:
            bpy.data.meshes.remove(body)
        return result

    @staticmethod
    def _validate_union_result(mesh: bpy.types.Mesh) -> None:
        """Reject empty, disconnected, non-manifold, or zero-volume ADDs."""

        if len(mesh.vertices) == 0 or len(mesh.polygons) == 0:
            raise ValueError("Boolean Add produced an empty mesh.")

        edge_faces: dict[tuple[int, int], list[int]] = {}
        for face_index, polygon in enumerate(mesh.polygons):
            if len(polygon.vertices) < 3:
                raise ValueError("Boolean Add produced a degenerate face.")
            vertices = tuple(polygon.vertices)
            for index, vertex_index in enumerate(vertices):
                edge = tuple(sorted((vertex_index, vertices[(index + 1) % len(vertices)])))
                edge_faces.setdefault(edge, []).append(face_index)

        face_neighbors: dict[int, set[int]] = {}
        for faces in edge_faces.values():
            for face_index in faces:
                face_neighbors.setdefault(face_index, set()).update(
                    neighbor for neighbor in faces if neighbor != face_index
                )

        components = 0
        visited: set[int] = set()
        for start in range(len(mesh.polygons)):
            if start in visited:
                continue
            components += 1
            stack = [start]
            visited.add(start)
            while stack:
                face_index = stack.pop()
                for neighbor in face_neighbors.get(face_index, ()):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        stack.append(neighbor)
        if components != 1:
            raise ValueError(
                f"Boolean Add must produce one connected solid; found {components} components."
            )

        import bmesh

        bmesh_data = bmesh.new()
        try:
            bmesh_data.from_mesh(mesh)
            if len(bmesh_data.verts) == 0 or len(bmesh_data.faces) == 0:
                raise ValueError("Boolean Add produced an empty mesh.")
            if any(edge.is_wire or not edge.is_manifold for edge in bmesh_data.edges):
                raise ValueError("Boolean Add produced a non-manifold solid.")
            try:
                volume = abs(float(bmesh_data.calc_volume(signed=False)))
            except TypeError:
                volume = abs(float(bmesh_data.calc_volume()))
            if volume <= 1e-12:
                raise ValueError("Boolean Add produced a zero-volume solid.")
        finally:
            bmesh_data.free()

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
        normal = sketch_normal(sketch)
        vertices: list[tuple[float, float, float]] = []
        faces: list[tuple[int, ...]] = []
        for points, _entity_ids in self._profile_loops_and_ids(profile):
            base = [sketch_to_world(sketch, u, v) for u, v in points]
            bottom = [
                tuple(point[index] + normal[index] * start_offset for index in range(3))
                for point in base
            ]
            top = [
                tuple(point[index] + normal[index] * end_offset for index in range(3))
                for point in base
            ]
            offset = len(vertices)
            count = len(points)
            vertices.extend(bottom + top)
            faces.extend(
                [
                    tuple(offset + index for index in reversed(range(count))),
                    tuple(offset + count + index for index in range(count)),
                ]
            )
            faces.extend(
                (
                    offset + index,
                    offset + (index + 1) % count,
                    offset + (index + 1) % count + count,
                    offset + index + count,
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
        loops = self._profile_loops_and_ids(profile)
        if not loops:
            raise ValueError(f"Unsupported profile kind: {profile.kind}")
        return loops[0]

    def _profile_loops_and_ids(
        self, profile: SketchProfile
    ) -> list[tuple[list[tuple[float, float]], list[str | None]]]:
        loops: list[tuple[list[tuple[float, float]], list[str | None]]] = []
        for loop in profile.iter_loops():
            if loop.points:
                points = list(loop.points)
                entity_ids: list[str | None] = list(loop.entity_ids)
            elif loop.circle is not None:
                cx, cy, radius = loop.circle
                points = [
                    (
                        cx + radius * cos(2.0 * pi * index / self.circle_segments),
                        cy + radius * sin(2.0 * pi * index / self.circle_segments),
                    )
                    for index in range(self.circle_segments)
                ]
                entity_ids = [None] * len(points)
            else:
                continue
            if len(points) < 3:
                raise ValueError("Closed profile requires at least three points.")
            if len(entity_ids) != len(points):
                entity_ids = [None] * len(points)
            signed_area = sum(
                points[index][0] * points[(index + 1) % len(points)][1]
                - points[(index + 1) % len(points)][0] * points[index][1]
                for index in range(len(points))
            )
            if signed_area < 0.0:
                points = list(reversed(points))
                entity_ids = list(reversed(entity_ids))
            loops.append((points, entity_ids))
        return loops
