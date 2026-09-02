from __future__ import annotations

import unittest
from math import pi

from blender_parametric_cad.core.evaluator import PartEvaluator
from blender_parametric_cad.core.part import Part
from blender_parametric_cad.features.extrude import ExtrudeFeature
from blender_parametric_cad.geometry.backend import GeometryBackend
from blender_parametric_cad.sketch.entities import SketchArc, SketchCircle, SketchLine
from blender_parametric_cad.sketch.numeric import set_rectangle
from blender_parametric_cad.sketch.sketch import SketchFeature

from .helpers import rectangle_sketch


class RecordingBackend(GeometryBackend):
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.sequence: list[str] = []

    def create_extrusion(self, sketch, profile, distance, direction):
        self.sequence.append("create_extrusion")
        result = {
            "distance": distance,
            "direction": direction,
            "width": max(point[0] for point in profile.points)
            - min(point[0] for point in profile.points),
        }
        self.calls.append(result)
        return result

    def create_extrusion_tool(self, sketch, profile, body, direction):
        self.sequence.append("create_extrusion_tool")
        tool = {
            "radius": profile.circle[2] if profile.circle else None,
            "profile_kind": profile.kind,
            "input_body": body,
        }
        self.calls.append(tool)
        return tool

    def boolean_difference(self, body, tool):
        self.sequence.append("boolean_difference")
        return {"outer": body, "hole_radius": tool.get("radius"), "removed": tool}

    def boolean_union(self, body, tool):
        self.sequence.append("boolean_union")
        return {"outer": body, "added": tool}


def cut_chain():
    base = rectangle_sketch()
    extrude = ExtrudeFeature(name="Extrude001", sketch_id=base.id, distance=0.02)
    hole = SketchFeature.on_feature_plane("Sketch002", extrude.id)
    hole.entities = [SketchCircle(cx=0.04, cy=0.025, radius=0.005)]
    cut = ExtrudeFeature(
        name="Cut001",
        sketch_id=hole.id,
        distance=0.0,
        operation="CUT",
        depth_mode="THROUGH_ALL",
        dependencies=[hole.id, extrude.id],
    )
    return Part(features=[base, extrude, hole, cut]), base, extrude, hole, cut


class RebuildTests(unittest.TestCase):
    def test_parameter_changes_are_re_evaluated_from_history(self) -> None:
        backend = RecordingBackend()
        sketch = rectangle_sketch()
        extrude = ExtrudeFeature(name="Extrude001", sketch_id=sketch.id, distance=0.02)
        part = Part(features=[sketch, extrude])
        evaluator = PartEvaluator(backend)

        first = evaluator.evaluate(part)
        extrude.distance = 0.04
        second = evaluator.evaluate(part)

        self.assertTrue(first.success and second.success)
        self.assertEqual([call["distance"] for call in backend.calls], [0.02, 0.04])

    def test_sketch_coordinate_change_updates_rebuilt_shape(self) -> None:
        backend = RecordingBackend()
        sketch = rectangle_sketch()
        extrude = ExtrudeFeature(name="Extrude001", sketch_id=sketch.id)
        part = Part(features=[sketch, extrude])
        evaluator = PartEvaluator(backend)

        evaluator.evaluate(part)
        for entity in sketch.entities:
            if entity.x1 == 0.08:
                entity.x1 = 0.10
            if entity.x2 == 0.08:
                entity.x2 = 0.10
        result = evaluator.evaluate(part)

        self.assertTrue(result.success)
        self.assertAlmostEqual(backend.calls[-1]["width"], 0.10)

    def test_invalid_open_profile_keeps_history_and_reports_error(self) -> None:
        backend = RecordingBackend()
        sketch = rectangle_sketch()
        sketch.entities = sketch.entities[:1]
        extrude = ExtrudeFeature(name="Extrude001", sketch_id=sketch.id)
        part = Part(features=[sketch, extrude])

        result = PartEvaluator(backend).evaluate(part)

        self.assertFalse(result.success)
        self.assertEqual(len(part.features), 2)
        self.assertEqual(extrude.status, "ERROR")
        self.assertIn("supported closed profile", extrude.error_message)

    def test_cut_evaluation_is_sequential_and_resolves_end_plane(self) -> None:
        backend = RecordingBackend()
        part, _base, extrude, hole, _cut = cut_chain()

        result = PartEvaluator(backend).evaluate(part)

        self.assertTrue(result.success)
        self.assertEqual(
            backend.sequence,
            ["create_extrusion", "create_extrusion_tool", "boolean_difference"],
        )
        self.assertEqual(result.context.resolved_planes[hole.id].origin, (0.0, 0.0, 0.02))
        extrude.distance = 0.04
        moved = PartEvaluator(RecordingBackend()).evaluate(part)
        self.assertEqual(moved.context.resolved_planes[hole.id].origin, (0.0, 0.0, 0.04))

    def test_cut_sketch_change_reaches_boolean_result(self) -> None:
        backend = RecordingBackend()
        part, _base, _extrude, hole, _cut = cut_chain()
        evaluator = PartEvaluator(backend)

        first = evaluator.evaluate(part)
        hole.entities[0].radius = 0.0075
        second = evaluator.evaluate(part)

        self.assertEqual(first.body["hole_radius"], 0.005)
        self.assertEqual(second.body["hole_radius"], 0.0075)

    def test_rollback_stops_after_selected_feature(self) -> None:
        backend = RecordingBackend()
        part, _base, _extrude, hole, cut = cut_chain()
        part.rollback_index = 1

        result = PartEvaluator(backend).evaluate(part)

        self.assertTrue(result.success)
        self.assertEqual(backend.sequence, ["create_extrusion"])
        self.assertEqual(hole.status, "NOT_EVALUATED")
        self.assertEqual(cut.status, "NOT_EVALUATED")

    def test_suppressed_cut_keeps_upstream_body(self) -> None:
        backend = RecordingBackend()
        part, _base, _extrude, _hole, cut = cut_chain()
        cut.suppressed = True

        result = PartEvaluator(backend).evaluate(part)

        self.assertTrue(result.success)
        self.assertEqual(backend.sequence, ["create_extrusion"])
        self.assertEqual(cut.status, "SUPPRESSED")
        self.assertEqual(result.body["distance"], 0.02)

    def test_suppressed_dependency_blocks_downstream_features(self) -> None:
        backend = RecordingBackend()
        part, _base, extrude, hole, cut = cut_chain()
        extrude.suppressed = True

        result = PartEvaluator(backend).evaluate(part)

        self.assertFalse(result.success)
        self.assertEqual(extrude.status, "SUPPRESSED")
        self.assertEqual(hole.status, "ERROR")
        self.assertIn("dependency", hole.error_message.lower())
        self.assertEqual(cut.status, "BLOCKED")
        self.assertIn("blocked", cut.error_message.lower())

    def test_cut_error_keeps_last_valid_body(self) -> None:
        backend = RecordingBackend()
        part, _base, _extrude, hole, cut = cut_chain()
        hole.entities.clear()

        result = PartEvaluator(backend).evaluate(part)

        self.assertFalse(result.success)
        self.assertEqual(cut.status, "ERROR")
        self.assertEqual(result.body["distance"], 0.02)

    def test_rectangle_and_triangle_remove_through_all(self) -> None:
        for shape in ("RECTANGLE", "TRIANGLE"):
            backend = RecordingBackend()
            base = rectangle_sketch()
            new = ExtrudeFeature(sketch_id=base.id, distance=0.02)
            tool_sketch = SketchFeature.on_feature_plane("Sketch002", new.id)
            if shape == "RECTANGLE":
                set_rectangle(tool_sketch, 0.03, 0.02, 0.02, 0.01)
            else:
                tool_sketch.entities = [
                    SketchLine(x1=0.03, y1=0.02, x2=0.05, y2=0.02),
                    SketchLine(x1=0.05, y1=0.02, x2=0.04, y2=0.04),
                    SketchLine(x1=0.04, y1=0.04, x2=0.03, y2=0.02),
                ]
            remove = ExtrudeFeature(
                sketch_id=tool_sketch.id,
                operation="REMOVE",
                depth_mode="THROUGH_ALL",
                dependencies=[tool_sketch.id, new.id],
            )

            result = PartEvaluator(backend).evaluate(
                Part(features=[base, new, tool_sketch, remove])
            )

            self.assertTrue(result.success, shape)
            self.assertEqual(backend.sequence[-2:], ["create_extrusion_tool", "boolean_difference"])

    def test_remove_blind_and_add_blind_use_generic_profile_tool(self) -> None:
        for operation, boolean_call in (
            ("REMOVE", "boolean_difference"),
            ("ADD", "boolean_union"),
        ):
            backend = RecordingBackend()
            base = rectangle_sketch()
            new = ExtrudeFeature(sketch_id=base.id, distance=0.02)
            tool_sketch = SketchFeature.on_feature_plane("Sketch002", new.id)
            set_rectangle(tool_sketch, 0.03, 0.02, 0.02, 0.01)
            feature = ExtrudeFeature(
                sketch_id=tool_sketch.id,
                distance=0.005 if operation == "REMOVE" else 0.010,
                direction=-1 if operation == "REMOVE" else 1,
                operation=operation,
                depth_mode="BLIND",
                dependencies=[tool_sketch.id, new.id],
            )

            result = PartEvaluator(backend).evaluate(
                Part(features=[base, new, tool_sketch, feature])
            )

            self.assertTrue(result.success, operation)
            self.assertEqual(backend.sequence[-2:], ["create_extrusion", boolean_call])

    def test_arc_and_split_region_profiles_reach_extrude_backend(self) -> None:
        backend = RecordingBackend()
        rounded = SketchFeature.on_plane("Rounded", "XY")
        rounded.entities = [
            SketchLine(x1=0.0, y1=0.0, x2=0.02, y2=0.0),
            SketchArc(cx=0.01, cy=0.0, radius=0.01, start_angle=0.0, end_angle=pi),
        ]
        feature = ExtrudeFeature(sketch_id=rounded.id, distance=0.01)
        rounded_result = PartEvaluator(backend).evaluate(
            Part(features=[rounded, feature])
        )
        self.assertTrue(rounded_result.success)

        split = rectangle_sketch()
        split.entities.append(SketchLine(x1=0.04, y1=0.0, x2=0.04, y2=0.05))
        split_feature = ExtrudeFeature(sketch_id=split.id, distance=0.01)
        split_result = PartEvaluator(RecordingBackend()).evaluate(
            Part(features=[split, split_feature])
        )
        self.assertTrue(split_result.success)


if __name__ == "__main__":
    unittest.main()
