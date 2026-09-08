"""M6.2 Revolve cap references without Blender topology dependencies."""

from __future__ import annotations

import unittest
import json
from math import radians, tau

from blender_parametric_cad.core.document import CadDocument
from blender_parametric_cad.core.evaluator import PartEvaluator
from blender_parametric_cad.core.part import Part
from blender_parametric_cad.core.references import AxisReference, TopoReference
from blender_parametric_cad.core.serialization import document_from_dict, document_to_dict
from blender_parametric_cad.features.revolve import RevolveFeature
from blender_parametric_cad.features.transform import TransformFeature
from blender_parametric_cad.sketch.entities import SketchLine
from blender_parametric_cad.sketch.numeric import set_rectangle
from blender_parametric_cad.sketch.plane import PlaneResolutionError, resolve_sketch_plane_from_history
from blender_parametric_cad.sketch.planar_faces import PlanarFaceResolver
from blender_parametric_cad.sketch.sketch import SketchFeature, sketch_normal

from .test_m5 import RecordingM5Backend
from .test_m6 import patch_on, polygon_mesh


class RevolveCapReferenceTests(unittest.TestCase):
    def _profile(self):
        sketch = SketchFeature.on_plane("Cone Profile", "XZ")
        set_rectangle(sketch, 0.010, -0.010, 0.030, 0.015)
        axis = SketchLine(
            x1=0.0,
            y1=-0.020,
            x2=0.0,
            y2=0.020,
            construction=True,
        )
        sketch.entities.append(axis)
        return sketch, axis

    def _partial_part(self):
        sketch, axis = self._profile()
        revolve = RevolveFeature(
            name="Partial Revolve",
            sketch_id=sketch.id,
            axis_reference=AxisReference(
                reference_type="SKETCH_LINE",
                sketch_id=sketch.id,
                entity_id=axis.id,
            ),
            angle=radians(180.0),
        )
        return Part(features=[sketch, revolve]), sketch, axis, revolve

    def test_partial_revolve_publishes_right_handed_start_and_end_caps(self):
        part, sketch, _axis, revolve = self._partial_part()
        result = PartEvaluator(RecordingM5Backend()).evaluate(part)

        self.assertTrue(result.success, result.errors)
        start = result.context.semantic_planes[(revolve.id, "START_CAP", None)]
        end = result.context.semantic_planes[(revolve.id, "END_CAP", None)]
        self.assertEqual(start.origin, sketch.origin)
        self.assertAlmostEqual(sum(end.x_axis[i] * end.y_axis[i] for i in range(3)), 0.0)
        cross = (
            end.x_axis[1] * end.y_axis[2] - end.x_axis[2] * end.y_axis[1],
            end.x_axis[2] * end.y_axis[0] - end.x_axis[0] * end.y_axis[2],
            end.x_axis[0] * end.y_axis[1] - end.x_axis[1] * end.y_axis[0],
        )
        self.assertAlmostEqual(
            sum(end.normal[i] * cross[i] for i in range(3)),
            1.0,
        )

    def test_sketch_line_axis_edit_moves_end_cap_but_keeps_reference_uuid(self):
        part, _sketch, axis, revolve = self._partial_part()
        support = SketchFeature.on_face(
            "End Cap Sketch", TopoReference(revolve.id, "END_CAP")
        )
        part.features.append(support)
        evaluator = PartEvaluator(RecordingM5Backend())

        first = evaluator.evaluate(part)
        first_origin = support.origin
        reference = support.plane_reference
        axis.x1 = axis.x2 = 0.005
        second = evaluator.evaluate(part)

        self.assertTrue(first.success, first.errors)
        self.assertTrue(second.success, second.errors)
        self.assertEqual(support.plane_reference, reference)
        self.assertNotEqual(first_origin, support.origin)

    def test_full_revolve_publishes_profile_line_top_and_bottom_caps(self):
        part, sketch, _axis, revolve = self._partial_part()
        revolve.angle = tau
        cap_lines = sorted(
            (
                entity
                for entity in sketch.entities
                if isinstance(entity, SketchLine)
                and not entity.construction
                and entity.y1 == entity.y2
            ),
            key=lambda entity: entity.id,
        )
        for index, line in enumerate(cap_lines):
            role = "START_CAP" if index == 0 else "END_CAP"
            part.features.append(
                SketchFeature.on_face(
                    f"Full Revolve Cap {index + 1}",
                    TopoReference(revolve.id, role, line.id),
                )
            )

        result = PartEvaluator(RecordingM5Backend()).evaluate(part)

        self.assertTrue(result.success, result.errors)
        cap_keys = {
            (role, source_entity_id)
            for feature_id, role, source_entity_id in result.context.semantic_planes
            if feature_id == revolve.id
        }
        self.assertEqual(
            cap_keys,
            {( "START_CAP", cap_lines[0].id), ("END_CAP", cap_lines[1].id)},
        )
        self.assertTrue(all(
            feature.status == "OK"
            for feature in part.features
            if feature.name.startswith("Full Revolve Cap")
        ))

    def test_full_revolve_publishes_no_caps_and_blocks_old_cap_sketch(self):
        part, _sketch, _axis, revolve = self._partial_part()
        support = SketchFeature.on_face(
            "End Cap Sketch", TopoReference(revolve.id, "END_CAP")
        )
        part.features.append(support)
        evaluator = PartEvaluator(RecordingM5Backend())
        self.assertTrue(evaluator.evaluate(part).success)

        revolve.angle = tau
        result = evaluator.evaluate(part)
        self.assertFalse(result.success)
        self.assertNotIn((revolve.id, "START_CAP", None), result.context.semantic_planes)
        self.assertEqual(support.status, "ERROR")
        self.assertIn("full 360-degree", support.error_message)
        with self.assertRaises(PlaneResolutionError):
            resolve_sketch_plane_from_history(part, support.id)

    def test_boolean_split_polygons_resolve_to_one_end_cap_reference(self):
        part, _sketch, _axis, revolve = self._partial_part()
        revolve.angle = radians(120.0)
        context = PartEvaluator(RecordingM5Backend()).evaluate(part).context
        plane = context.semantic_planes[(revolve.id, "END_CAP", None)]
        context.current_body = polygon_mesh([patch_on(plane), patch_on(plane, .01, .01)])

        resolver = PlanarFaceResolver()
        first = resolver.resolve_polygon(0, context)
        second = resolver.resolve_polygon(1, context)
        self.assertEqual(first, second)
        self.assertEqual((first.feature_id, first.role), (revolve.id, "END_CAP"))

    def test_transform_updates_cap_and_downstream_sketch(self):
        part, _sketch, _axis, revolve = self._partial_part()
        transform = TransformFeature(
            name="Tilt Revolve",
            rotation=(0.0, radians(-12.0), 0.0),
            dependencies=[revolve.id],
        )
        support = SketchFeature.on_face(
            "Tilted End Cap Sketch", TopoReference(revolve.id, "END_CAP")
        )
        part.features.extend([transform, support])
        evaluator = PartEvaluator(RecordingM5Backend())

        first = evaluator.evaluate(part)
        first_axes = (support.x_axis, support.y_axis, sketch_normal(support))
        transform.rotation = (0.0, radians(-8.0), 0.0)
        second = evaluator.evaluate(part)

        self.assertTrue(first.success, first.errors)
        self.assertTrue(second.success, second.errors)
        self.assertNotEqual(first_axes, (support.x_axis, support.y_axis, sketch_normal(support)))
        self.assertEqual(
            support.origin,
            second.context.semantic_planes[(revolve.id, "END_CAP", None)].origin,
        )

    def test_cap_reference_survives_serialization_and_history_resolution(self):
        part, _sketch, _axis, revolve = self._partial_part()
        support = SketchFeature.on_face(
            "Saved End Cap Sketch", TopoReference(revolve.id, "END_CAP")
        )
        part.features.append(support)
        restored = document_from_dict(document_to_dict(CadDocument(parts=[part]))).parts[0]
        result = PartEvaluator(RecordingM5Backend()).evaluate(restored)

        self.assertTrue(result.success, result.errors)
        plane = resolve_sketch_plane_from_history(restored, support.id)
        self.assertEqual(plane.origin, restored.get_feature(support.id).origin)
        self.assertNotIn("polygon_index", json.dumps(
            document_to_dict(CadDocument(parts=[restored]))
        ))


if __name__ == "__main__":
    unittest.main()
