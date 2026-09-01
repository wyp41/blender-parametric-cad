from __future__ import annotations

import unittest

from blender_parametric_cad.core.document import CadDocument
from blender_parametric_cad.core.part import Part
from blender_parametric_cad.sketch.entities import SketchCircle, SketchLine
from blender_parametric_cad.sketch.numeric import (
    circle_parameters,
    rectangle_parameters,
    set_circle,
    set_rectangle,
)
from blender_parametric_cad.sketch.profile import ProfileDetector
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


if __name__ == "__main__":
    unittest.main()
