"""Tessellated Blender mesh backend for M2 visualization."""

from __future__ import annotations

from math import cos, pi, sin

import bpy

from ..sketch.profile import SketchProfile
from ..sketch.sketch import SketchFeature, sketch_normal, sketch_to_world
from .backend import GeometryBackend


class BlenderMeshBackend(GeometryBackend):
    """Build a new disposable Blender Mesh for each history evaluation."""

    circle_segments = 64

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
        if profile.points:
            return list(profile.points)
        if profile.kind == "CIRCLE" and profile.circle is not None:
            cx, cy, radius = profile.circle
            return [
                (
                    cx + radius * cos(2.0 * pi * index / self.circle_segments),
                    cy + radius * sin(2.0 * pi * index / self.circle_segments),
                )
                for index in range(self.circle_segments)
            ]
        raise ValueError(f"Unsupported profile kind: {profile.kind}")
