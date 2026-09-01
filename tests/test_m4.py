from __future__ import annotations

import unittest
from math import tau

from blender_parametric_cad.core.evaluator import PartEvaluator
from blender_parametric_cad.core.part import Part
from blender_parametric_cad.core.references import AxisReference, TopoReference
from blender_parametric_cad.features.extrude import ExtrudeFeature
from blender_parametric_cad.features.revolve import RevolveFeature
from blender_parametric_cad.geometry.backend import GeometryBackend
from blender_parametric_cad.sketch.entities import SketchLine
from blender_parametric_cad.sketch.numeric import set_rectangle
from blender_parametric_cad.sketch.plane import resolve_sketch_plane_from_history
from blender_parametric_cad.sketch.sketch import SketchFeature

from .helpers import rectangle_sketch


class RecordingM4Backend(GeometryBackend):
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def create_extrusion(self, sketch, profile, distance, direction):
        body = {"kind": "extrude", "distance": distance}
        self.calls.append(("extrude", body))
        return body

    def revolve_profile(self, sketch, profile, axis_origin, axis_direction, angle):
        body = {
            "kind": "revolve",
            "profile": profile.kind,
            "axis_origin": axis_origin,
            "axis_direction": axis_direction,
            "angle": angle,
        }
        self.calls.append(("revolve", body))
        return body

    def boolean_union(self, body, tool):
        result = {"kind": "union", "body": body, "tool": tool}
        self.calls.append(("union", result))
        return result

    def boolean_difference(self, body, tool):
        result = {"kind": "difference", "body": body, "tool": tool}
        self.calls.append(("difference", result))
        return result


class M4SemanticReferenceTests(unittest.TestCase):
    def test_end_and_side_face_planes_follow_source_parameters(self) -> None:
        base = rectangle_sketch()
        extrude = ExtrudeFeature(sketch_id=base.id, distance=0.02)
        end = SketchFeature.on_face("End", TopoReference(extrude.id, "END_FACE"))
        side_id = base.entities[0].id
        side = SketchFeature.on_face(
            "Side", TopoReference(extrude.id, "SIDE_FACE", side_id)
        )
        part = Part(features=[base, extrude, end, side])

        end_plane = resolve_sketch_plane_from_history(part, end.id)
        side_plane = resolve_sketch_plane_from_history(part, side.id)
        self.assertEqual(end_plane.origin, (0.0, 0.0, 0.02))
        self.assertEqual(side_plane.origin, (0.0, 0.0, 0.0))
        self.assertEqual(side_plane.y_axis, (0.0, 0.0, 1.0))

        extrude.distance = 0.04
        set_rectangle(base, -0.05, -0.03, 0.10, 0.06)
        moved_end = resolve_sketch_plane_from_history(part, end.id)
        moved_side = resolve_sketch_plane_from_history(part, side.id)
        self.assertEqual(moved_end.origin, (0.0, 0.0, 0.04))
        self.assertEqual(moved_side.origin, (-0.05, -0.03, 0.0))

    def test_face_and_axis_references_round_trip_without_mesh_indices(self) -> None:
        base = rectangle_sketch()
        extrude = ExtrudeFeature(sketch_id=base.id, distance=0.02)
        face_sketch = SketchFeature.on_face(
            "Face Sketch", TopoReference(extrude.id, "END_FACE")
        )
        axis = AxisReference(
            reference_type="SKETCH_LINE", sketch_id=face_sketch.id, entity_id=base.entities[0].id
        )
        revolve = RevolveFeature(
            sketch_id=face_sketch.id,
            axis_reference=axis,
            angle=tau,
            operation="NEW",
        )
        from blender_parametric_cad.core.document import CadDocument

        document = CadDocument(parts=[Part(features=[base, extrude, face_sketch, revolve])])
        round_trip = CadDocument.from_dict(document.to_dict()).parts[0]
        restored_sketch = round_trip.get_feature(face_sketch.id)
        restored_revolve = round_trip.get_feature(revolve.id)
        self.assertEqual(restored_sketch.plane_reference.role, "END_FACE")
        self.assertEqual(restored_revolve.axis_reference.reference_type, "SKETCH_LINE")
        self.assertNotIn("polygon_index", str(document.to_dict()))
        self.assertNotIn("face_index", str(document.to_dict()))


class M4RevolveEvaluationTests(unittest.TestCase):
    def _profile(self) -> tuple[SketchFeature, SketchLine]:
        sketch = SketchFeature.on_plane("Profile", "XZ")
        set_rectangle(sketch, 0.0, 0.0, 0.01, 0.02)
        axis = SketchLine(x1=0.0, y1=0.0, x2=0.0, y2=0.02, construction=True)
        sketch.entities.append(axis)
        return sketch, axis

    def test_datum_axis_revolve_new(self) -> None:
        sketch, _axis = self._profile()
        revolve = RevolveFeature(
            sketch_id=sketch.id,
            axis_reference=AxisReference(axis="Z"),
            angle=tau,
        )
        backend = RecordingM4Backend()
        result = PartEvaluator(backend).evaluate(Part(features=[sketch, revolve]))
        self.assertTrue(result.success)
        self.assertEqual(backend.calls[-1][0], "revolve")
        self.assertEqual(backend.calls[-1][1]["axis_direction"], (0.0, 0.0, 1.0))

    def test_sketch_line_axis_rebuild_uses_same_uuid(self) -> None:
        sketch, axis = self._profile()
        revolve = RevolveFeature(
            sketch_id=sketch.id,
            axis_reference=AxisReference(
                reference_type="SKETCH_LINE", sketch_id=sketch.id, entity_id=axis.id
            ),
            angle=tau,
        )
        backend = RecordingM4Backend()
        first = PartEvaluator(backend).evaluate(Part(features=[sketch, revolve]))
        self.assertTrue(first.success)
        axis.x1 = axis.x2 = 0.003
        second = PartEvaluator(backend).evaluate(Part(features=[sketch, revolve]))
        self.assertTrue(second.success)
        self.assertEqual(second.body["axis_origin"][0], 0.003)
        self.assertEqual(revolve.axis_reference.entity_id, axis.id)

    def test_revolve_add_and_remove_require_and_use_existing_body(self) -> None:
        base = rectangle_sketch()
        new = ExtrudeFeature(sketch_id=base.id, distance=0.02)
        profile, _axis = self._profile()
        add = RevolveFeature(
            sketch_id=profile.id,
            axis_reference=AxisReference(axis="Z"),
            operation="ADD",
            dependencies=[profile.id, new.id],
        )
        backend = RecordingM4Backend()
        result = PartEvaluator(backend).evaluate(Part(features=[base, new, profile, add]))
        self.assertTrue(result.success)
        self.assertEqual(backend.calls[-1][0], "union")

        remove = RevolveFeature(
            sketch_id=profile.id,
            axis_reference=AxisReference(axis="Z"),
            operation="REMOVE",
            dependencies=[profile.id, new.id],
        )
        backend = RecordingM4Backend()
        result = PartEvaluator(backend).evaluate(
            Part(features=[base, new, profile, remove])
        )
        self.assertTrue(result.success)
        self.assertEqual(backend.calls[-1][0], "difference")


if __name__ == "__main__":
    unittest.main()
