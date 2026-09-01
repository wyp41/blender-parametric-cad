from __future__ import annotations

import unittest
from math import pi

from blender_parametric_cad.core.document import CadDocument
from blender_parametric_cad.core.part import Part
from blender_parametric_cad.sketch.entities import SketchArc, SketchCircle, SketchLine
from blender_parametric_cad.sketch.numeric import (
    arc_parameters,
    circle_parameters,
    rectangle_parameters,
    set_arc,
    set_circle,
    set_rectangle,
)
from blender_parametric_cad.sketch.profile import ProfileDetector
from blender_parametric_cad.sketch.snapping import intersection_points, snap_point
from blender_parametric_cad.sketch.sketch import SketchFeature

from .helpers import rectangle_sketch


class SketchTests(unittest.TestCase):
    def test_rectangle_entities_survive_document_round_trip(self) -> None:
        sketch = rectangle_sketch()
        document = CadDocument(parts=[Part(features=[sketch])])
        restored = CadDocument.from_dict(document.to_dict())
        restored_sketch = restored.parts[0].features[0]
        self.assertEqual(len(restored_sketch.entities), 4)
        self.assertIsInstance(restored_sketch.entities[0], SketchLine)
        self.assertEqual(restored_sketch.entities[1].x1, 0.08)

    def test_sketch_coordinates_map_to_selected_plane(self) -> None:
        from blender_parametric_cad.sketch.sketch import SketchFeature, sketch_to_world

        sketch = SketchFeature.on_plane("Sketch001", "XZ")
        self.assertEqual(sketch_to_world(sketch, 0.08, 0.05), (0.08, 0.0, 0.05))

    def test_arc_entities_survive_document_round_trip(self) -> None:
        sketch = SketchFeature.on_plane("ArcSketch", "XY")
        sketch.entities = [
            SketchLine(x1=0.0, y1=0.0, x2=0.02, y2=0.0),
            SketchArc(cx=0.01, cy=0.0, radius=0.01, start_angle=0.0, end_angle=pi),
        ]
        document = CadDocument(parts=[Part(features=[sketch])])
        restored = CadDocument.from_dict(document.to_dict()).parts[0].features[0]
        self.assertIsInstance(restored.entities[1], SketchArc)
        self.assertEqual(restored.entities[1].end_angle, pi)


class ProfileDetectionTests(unittest.TestCase):
    def test_rectangle_is_valid(self) -> None:
        result = ProfileDetector().detect(rectangle_sketch())
        self.assertTrue(result.success)
        self.assertEqual(result.profile.kind, "RECTANGLE")

    def test_circle_is_valid(self) -> None:
        sketch = rectangle_sketch()
        sketch.entities = [SketchCircle(cx=0.0, cy=0.0, radius=0.02)]
        result = ProfileDetector().detect(sketch)
        self.assertTrue(result.success)
        self.assertEqual(result.profile.kind, "CIRCLE")

    def test_multiple_circles_form_a_composite_profile(self) -> None:
        sketch = SketchFeature.on_plane("Circles", "XY")
        sketch.entities = [
            SketchCircle(cx=-0.02, cy=0.0, radius=0.01),
            SketchCircle(cx=0.02, cy=0.0, radius=0.01),
        ]
        result = ProfileDetector().detect(sketch)
        self.assertTrue(result.success)
        self.assertEqual(result.profile.kind, "COMPOSITE")
        self.assertEqual(len(result.profile.loops), 2)

    def test_circle_and_closed_loop_can_be_combined(self) -> None:
        sketch = rectangle_sketch()
        sketch.entities.append(SketchCircle(cx=0.12, cy=0.0, radius=0.01))
        result = ProfileDetector().detect(sketch)
        self.assertTrue(result.success)
        self.assertEqual(result.profile.kind, "COMPOSITE")
        self.assertEqual(len(result.profile.loops), 2)

    def test_open_line_is_invalid(self) -> None:
        sketch = rectangle_sketch()
        sketch.entities = [SketchLine(x1=0.0, y1=0.0, x2=0.08, y2=0.0)]
        result = ProfileDetector().detect(sketch)
        self.assertFalse(result.success)
        self.assertIn("supported closed profile", result.message)

    def test_triangle_and_simple_polygon_are_valid(self) -> None:
        triangle = SketchFeature.on_plane("Triangle", "XY")
        triangle.entities = [
            SketchLine(x1=0.0, y1=0.0, x2=0.02, y2=0.0),
            SketchLine(x1=0.02, y1=0.0, x2=0.01, y2=0.02),
            SketchLine(x1=0.01, y1=0.02, x2=0.0, y2=0.0),
        ]
        result = ProfileDetector().detect(triangle)
        self.assertTrue(result.success)
        self.assertEqual(result.profile.kind, "POLYGON")
        self.assertEqual(len(result.profile.points), 3)

    def test_mixed_arc_and_line_loop_is_valid(self) -> None:
        sketch = SketchFeature.on_plane("Rounded", "XY")
        sketch.entities = [
            SketchLine(x1=0.0, y1=0.0, x2=0.02, y2=0.0),
            SketchArc(
                cx=0.01,
                cy=0.0,
                radius=0.01,
                start_angle=0.0,
                end_angle=pi,
            ),
        ]
        result = ProfileDetector().detect(sketch)
        self.assertTrue(result.success)
        self.assertEqual(result.profile.kind, "ARC_LOOP")
        self.assertGreater(len(result.profile.points), 3)

    def test_split_line_produces_deletable_regions(self) -> None:
        sketch = rectangle_sketch()
        split = SketchLine(x1=0.0, y1=0.0, x2=0.08, y2=0.05)
        sketch.entities.append(split)
        detector = ProfileDetector()
        result = detector.detect(sketch)
        self.assertTrue(result.success)
        self.assertEqual(result.profile.kind, "COMPOSITE")
        self.assertEqual(len(result.profile.loops), 2)
        sketch.deleted_regions.append(result.profile.loops[0].region_id)
        remaining = detector.detect(sketch)
        self.assertTrue(remaining.success)
        self.assertEqual(len(remaining.profile.loops), 1)
        restored = CadDocument.from_dict(
            CadDocument(parts=[Part(features=[sketch])]).to_dict()
        ).parts[0].features[0]
        self.assertEqual(restored.deleted_regions, sketch.deleted_regions)

    def test_split_line_can_end_on_edge_midpoints(self) -> None:
        sketch = rectangle_sketch()
        sketch.entities.append(SketchLine(x1=0.04, y1=0.0, x2=0.04, y2=0.05))
        result = ProfileDetector().detect(sketch)
        self.assertTrue(result.success)
        self.assertEqual(len(result.profile.loops), 2)

    def test_intersections_are_reported_and_prioritized_by_snapping(self) -> None:
        entities = [
            SketchLine(x1=0.0, y1=0.0, x2=0.08, y2=0.08),
            SketchLine(x1=0.0, y1=0.08, x2=0.08, y2=0.0),
        ]
        points = intersection_points(entities)
        self.assertEqual(len(points), 1)
        self.assertAlmostEqual(points[0][0], 0.04)
        self.assertAlmostEqual(points[0][1], 0.04)
        self.assertEqual(snap_point(entities, (0.0405, 0.0395), 0.002), points[0])

    def test_arc_intersection_is_snap_target(self) -> None:
        arc = SketchArc(cx=0.04, cy=0.04, radius=0.02, start_angle=0.0, end_angle=pi)
        line = SketchLine(x1=0.0, y1=0.04, x2=0.08, y2=0.04)
        points = intersection_points([arc, line])
        self.assertEqual(len(points), 2)
        self.assertEqual(snap_point([arc, line], (0.0605, 0.0402), 0.002), (0.06, 0.04))

    def test_branching_and_self_intersecting_lines_are_invalid(self) -> None:
        branching = rectangle_sketch()
        branching.entities.append(SketchLine(x1=0.0, y1=0.0, x2=-0.01, y2=0.0))
        self.assertFalse(ProfileDetector().detect(branching).success)

        crossing = SketchFeature.on_plane("Crossing", "XY")
        crossing.entities = [
            SketchLine(x1=0.0, y1=0.0, x2=0.02, y2=0.02),
            SketchLine(x1=0.02, y1=0.02, x2=0.0, y2=0.02),
            SketchLine(x1=0.0, y1=0.02, x2=0.02, y2=0.0),
            SketchLine(x1=0.02, y1=0.0, x2=0.0, y2=0.0),
        ]
        self.assertFalse(ProfileDetector().detect(crossing).success)


class NumericSketchTests(unittest.TestCase):
    def test_rectangle_creation_and_edit_preserve_line_uuids(self) -> None:
        sketch = SketchFeature.on_plane("Sketch001", "XY")
        set_rectangle(sketch, -0.04, -0.025, 0.08, 0.05)
        entity_ids = [entity.id for entity in sketch.entities]

        set_rectangle(sketch, -0.05, -0.03, 0.10, 0.06)

        self.assertEqual([entity.id for entity in sketch.entities], entity_ids)
        self.assertEqual(rectangle_parameters(sketch), (-0.05, -0.03, 0.10, 0.06))

    def test_circle_creation_and_edit_preserve_uuid(self) -> None:
        sketch = SketchFeature.on_plane("Sketch001", "XY")
        set_circle(sketch, 0.0, 0.0, 0.01)
        circle_id = sketch.entities[0].id

        set_circle(sketch, 0.001, -0.002, 0.015)

        self.assertEqual(sketch.entities[0].id, circle_id)
        self.assertEqual(circle_parameters(sketch), (0.001, -0.002, 0.015))

    def test_arc_creation_and_edit_preserve_uuid(self) -> None:
        sketch = SketchFeature.on_plane("ArcSketch", "XY")
        set_arc(sketch, 0.0, 0.0, 0.01, 0.0, pi / 2.0)
        arc_id = sketch.entities[0].id
        set_arc(sketch, 0.001, -0.002, 0.015, pi / 4.0, pi, arc_id)
        self.assertEqual(sketch.entities[0].id, arc_id)
        self.assertEqual(
            arc_parameters(sketch, arc_id),
            (0.001, -0.002, 0.015, pi / 4.0, pi),
        )


if __name__ == "__main__":
    unittest.main()
