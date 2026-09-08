"""M6 history and polygon matching checks without launching Blender.

Mesh fixtures represent Boolean outputs; they do not test Blender's Boolean
implementation or its viewport event loop.
"""
from __future__ import annotations

import unittest
from math import radians
from types import SimpleNamespace

from blender_parametric_cad.core.document import CadDocument
from blender_parametric_cad.core.evaluator import PartEvaluator
from blender_parametric_cad.core.part import Part
from blender_parametric_cad.core.serialization import dumps, loads
from blender_parametric_cad.features.extrude import ExtrudeFeature
from blender_parametric_cad.features.transform import TransformFeature
from blender_parametric_cad.features.mirror import MirrorFeature
from blender_parametric_cad.sketch.plane import PlaneReference, PlaneResolver, resolve_sketch_plane_from_history
from blender_parametric_cad.sketch.planar_faces import PlanarFaceResolver
from blender_parametric_cad.sketch.sketch import SketchFeature
from .helpers import rectangle_sketch
from .test_m5 import RecordingM5Backend


def polygon_mesh(polygons):
    vertices, faces = [], []
    for points, normal in polygons:
        indices = list(range(len(vertices), len(vertices) + len(points)))
        vertices.extend(SimpleNamespace(co=p) for p in points)
        faces.append(SimpleNamespace(index=len(faces), vertices=indices, normal=normal))
    return SimpleNamespace(vertices=vertices, polygons=faces)


def patch_on(plane, u=0.0, v=0.0):
    return ([tuple(plane.origin[i] + x * plane.x_axis[i] + y * plane.y_axis[i]
                   for i in range(3))
             for x, y in [(u, v), (u + .002, v), (u + .002, v + .002), (u, v + .002)]],
            plane.normal)


class PlanarReferenceTests(unittest.TestCase):
    def base(self):
        sketch = rectangle_sketch()
        extrude = ExtrudeFeature(name="Base", sketch_id=sketch.id, distance=.02)
        return Part(features=[sketch, extrude]), sketch, extrude

    def evaluate(self, part):
        result = PartEvaluator(RecordingM5Backend()).evaluate(part)
        self.assertTrue(result.success, result.errors)
        return result.context

    def test_boolean_split_top_and_json_reload_follow_distance(self):
        part, base, extrude = self.base()
        hole = rectangle_sketch(.005, .005)
        remove = ExtrudeFeature(name="Hole", sketch_id=hole.id, distance=.02,
                                operation="REMOVE", depth_mode="THROUGH_ALL")
        part.features.extend([hole, remove])
        context = self.evaluate(part)
        plane = context.semantic_planes[(extrude.id, "END_PLANE", None)]
        context.current_body = polygon_mesh([patch_on(plane), patch_on(plane, .01, .01)])
        resolver = PlanarFaceResolver()
        refs = [resolver.resolve_polygon(i, context) for i in range(2)]
        self.assertEqual(refs[0], refs[1])
        self.assertEqual((refs[0].feature_id, refs[0].role), (extrude.id, "END_PLANE"))
        support = SketchFeature(name="Top", plane_reference=refs[0])
        part.features.append(support)
        doc = CadDocument(parts=[part], active_part_id=part.id)
        data = dumps(doc)
        for forbidden in ("polygon_index", "face_index", "edge_index"):
            self.assertNotIn(forbidden, data)
        restored = loads(data).parts[0]
        restored.features[1].distance = .035
        self.evaluate(restored)
        self.assertAlmostEqual(restored.features[-1].origin[2], .035)
        self.assertEqual(resolve_sketch_plane_from_history(restored, support.id).origin,
                         restored.features[-1].origin)

    def test_each_side_uses_line_uuid_and_follows_rectangle_resize(self):
        part, sketch, extrude = self.base()
        context = self.evaluate(part)
        resolver = PlanarFaceResolver()
        for line in sketch.entities:
            plane = context.semantic_planes[(extrude.id, "SIDE_FACE", line.id)]
            context.current_body = polygon_mesh([patch_on(plane)])
            ref = resolver.resolve_polygon(0, context)
            self.assertEqual(ref.source_entity_id, line.id)
            support = SketchFeature(name="Side", plane_reference=ref)
            part.features.append(support)
        from blender_parametric_cad.sketch.numeric import set_rectangle
        set_rectangle(sketch, 0, 0, .12, .09)
        context = self.evaluate(part)
        for support in part.features[2:]:
            resolved = PlaneResolver().resolve(support.plane_reference, context)
            self.assertEqual(support.origin, resolved.origin)
        self.assertAlmostEqual(part.features[3].origin[0], .12)

    def test_rectangle_edit_preserves_selected_line_uuid_edge(self):
        sketch = rectangle_sketch()
        line_ids = [line.id for line in sketch.entities]
        from blender_parametric_cad.sketch.numeric import set_rectangle

        set_rectangle(sketch, .010, .020, .030, .040, entity_id=line_ids[1])
        edges = {
            line.id: (line.x1, line.y1, line.x2, line.y2)
            for line in sketch.entities
        }
        self.assertEqual(edges[line_ids[0]], (.010, .020, .040, .020))
        self.assertEqual(edges[line_ids[1]], (.040, .020, .040, .060))
        self.assertEqual(edges[line_ids[2]], (.040, .060, .010, .060))
        self.assertEqual(edges[line_ids[3]], (.010, .060, .010, .020))

    def test_transform_selection_and_parameter_change(self):
        part, sketch, extrude = self.base()
        transform = TransformFeature(name="Tilt", rotation=(0, radians(-12), 0))
        part.features.append(transform)
        context = self.evaluate(part)
        plane = context.semantic_planes[(extrude.id, "END_PLANE", None)]
        context.current_body = polygon_mesh([patch_on(plane)])
        ref = PlanarFaceResolver().resolve_polygon(0, context)
        support = SketchFeature(name="Tilted", plane_reference=ref)
        part.features.append(support)
        self.evaluate(part)
        old = support.origin
        transform.rotation = (0, radians(-8), 0)
        context = self.evaluate(part)
        self.assertNotEqual(old, support.origin)
        self.assertEqual(support.origin, context.semantic_planes[(extrude.id, "END_PLANE", None)].origin)
        self.assertEqual(resolve_sketch_plane_from_history(part, support.id).x_axis, support.x_axis)

    def test_mirror_plane_persists_through_later_transform(self):
        part, sketch, extrude = self.base()
        profile = rectangle_sketch(.01, .01)
        add = ExtrudeFeature(name="Add", sketch_id=profile.id, distance=.03, operation="ADD")
        mirror = MirrorFeature(name="Mirror", source_feature_id=add.id)
        part.features.extend([profile, add, mirror])
        context = self.evaluate(part)
        key = (mirror.id, "SIDE_FACE", profile.entities[1].id)
        plane = context.semantic_planes[key]
        context.current_body = polygon_mesh([patch_on(plane)])
        ref = PlanarFaceResolver().resolve_polygon(0, context)
        self.assertEqual(ref.feature_id, mirror.id)
        transform = TransformFeature(name="Move", translation=(.1, .2, .3))
        part.features.extend([transform, SketchFeature(name="Mirrored", plane_reference=ref)])
        restored = loads(dumps(CadDocument(parts=[part]))).parts[0]
        context = self.evaluate(restored)
        self.assertEqual(restored.features[-1].origin, context.semantic_planes[key].origin)
        self.assertEqual(resolve_sketch_plane_from_history(restored, restored.features[-1].id).origin,
                         restored.features[-1].origin)

    def test_nonplanar_and_unmapped_faces_are_unsupported(self):
        part, sketch, extrude = self.base()
        context = self.evaluate(part)
        context.current_body = polygon_mesh([
            ([(1, 1, 1), (2, 1, 1), (2, 2, 1)], (0, 0, 1)),
            ([(0, 0, .02), (.01, 0, .02), (.01, .01, .021), (0, .01, .02)], (0, 0, 1)),
        ])
        resolver = PlanarFaceResolver()
        self.assertTrue(resolver.candidate(0, context).planar)
        self.assertFalse(resolver.candidate(1, context).planar)
        self.assertIsNone(resolver.resolve_polygon(0, context))
        self.assertIsNone(resolver.resolve_polygon(1, context))

    def test_remove_preserves_side_and_exact_provenance_has_priority(self):
        from blender_parametric_cad.core.references import TopoReference
        part, sketch, extrude = self.base()
        cut = rectangle_sketch(.005, .005)
        remove = ExtrudeFeature(name="Pocket", sketch_id=cut.id,
                                operation="REMOVE", distance=.01)
        part.features.extend([cut, remove])
        context = self.evaluate(part)
        key = (extrude.id, "SIDE_FACE", sketch.entities[1].id)
        plane = context.semantic_planes[key]
        context.current_body = polygon_mesh([patch_on(plane), patch_on(plane, .01)])
        resolver = PlanarFaceResolver()
        self.assertEqual(resolver.resolve_polygon(0, context), resolver.resolve_polygon(1, context))
        self.assertEqual(resolver.resolve_polygon(0, context).source_entity_id, key[2])
        # Two historical producers may share a plane. Exact provenance wins;
        # absent provenance, history insertion order is deterministic.
        other = (remove.id, "SIDE_FACE", cut.entities[1].id)
        context.semantic_planes[other] = plane
        context.face_provenance[0] = TopoReference(*other)
        self.assertEqual(resolver.resolve_polygon(0, context).feature_id, remove.id)

    def test_rollback_and_suppression_do_not_publish_future_planes(self):
        part, sketch, extrude = self.base()
        transform = TransformFeature(name="Move", translation=(.1, 0, 0))
        part.features.append(transform)
        part.rollback_index = 1
        context = self.evaluate(part)
        self.assertAlmostEqual(context.semantic_planes[(extrude.id, "END_PLANE", None)].origin[0], 0)
        part.rollback_index = None
        transform.suppressed = True
        context = self.evaluate(part)
        self.assertAlmostEqual(context.semantic_planes[(extrude.id, "END_PLANE", None)].origin[0], 0)

    def test_frame_is_right_handed_after_mirror(self):
        part, sketch, extrude = self.base()
        profile = rectangle_sketch(.01, .01)
        add = ExtrudeFeature(name="Add", sketch_id=profile.id, distance=.03, operation="ADD")
        mirror = MirrorFeature(name="Mirror", source_feature_id=add.id)
        part.features.extend([profile, add, mirror])
        context = self.evaluate(part)
        for (producer, _, _), plane in context.semantic_planes.items():
            if producer != mirror.id:
                continue
            x, y = plane.x_axis, plane.y_axis
            cross = (x[1]*y[2]-x[2]*y[1], x[2]*y[0]-x[0]*y[2], x[0]*y[1]-x[1]*y[0])
            for actual, expected in zip(cross, plane.normal):
                self.assertAlmostEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
