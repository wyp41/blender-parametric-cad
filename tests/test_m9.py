from __future__ import annotations

import unittest

from blender_parametric_cad.core.document import CadDocument
from blender_parametric_cad.core.part import Part
from blender_parametric_cad.core.references import SketchEntityReference
from blender_parametric_cad.core.serialization import document_from_dict, document_to_dict
from blender_parametric_cad.sketch.dimensions import (
    DIAMETER,
    DISTANCE,
    HORIZONTAL_DISTANCE,
    LENGTH,
    RADIUS,
    VERTICAL_DISTANCE,
    DimensionError,
    SketchDimension,
    apply_dimension,
    dimension_value,
    remove_dimensions_for_entity,
    validate_dimension_conflicts,
)
from blender_parametric_cad.sketch.entities import SketchCircle, SketchLine
from blender_parametric_cad.sketch.sketch import SketchFeature
from blender_parametric_cad.sketch.solver import SketchSolver


class SketchDimensionTests(unittest.TestCase):
    def _line_sketch(self):
        sketch = SketchFeature.on_plane("Dimension Sketch", "XY")
        line = SketchLine(x1=0.0, y1=0.0, x2=0.080, y2=0.030)
        other = SketchLine(x1=0.0, y1=0.040, x2=0.050, y2=0.040)
        sketch.entities.extend((line, other))
        return sketch, line, other

    @staticmethod
    def _ref(sketch, entity, sub="ENTITY"):
        return SketchEntityReference(sketch.id, entity.id, sub)

    def test_length_edit_preserves_line_uuid_and_direction(self):
        sketch, line, _other = self._line_sketch()
        original_id = line.id
        dimension = SketchDimension(
            dimension_type=LENGTH,
            entity_refs=[self._ref(sketch, line)],
            value=0.100,
        )
        self.assertAlmostEqual(dimension_value(sketch, dimension), (0.080**2 + 0.030**2) ** 0.5)
        apply_dimension(sketch, dimension, 0.100)
        self.assertEqual(line.id, original_id)
        self.assertAlmostEqual(dimension_value(sketch, dimension), 0.100)
        self.assertGreater(line.x2, line.x1)
        self.assertGreater(line.y2, line.y1)

    def test_horizontal_vertical_and_direct_distance_move_only_second_point(self):
        sketch, line, other = self._line_sketch()
        start = self._ref(sketch, line, "START")
        end = self._ref(sketch, line, "END")
        original_start = (line.x1, line.y1)
        horizontal = SketchDimension(
            dimension_type=HORIZONTAL_DISTANCE,
            entity_refs=[start, end],
            value=0.120,
        )
        apply_dimension(sketch, horizontal, 0.120)
        self.assertEqual((line.x1, line.y1), original_start)
        self.assertAlmostEqual(line.x2, 0.120)
        self.assertAlmostEqual(line.y2, 0.030)
        vertical = SketchDimension(
            dimension_type=VERTICAL_DISTANCE,
            entity_refs=[self._ref(sketch, other, "START"), self._ref(sketch, other, "END")],
            value=0.025,
        )
        apply_dimension(sketch, vertical, 0.025)
        self.assertAlmostEqual(other.x2, 0.050)
        self.assertAlmostEqual(other.y2, 0.065)
        direct = SketchDimension(
            dimension_type=DISTANCE,
            entity_refs=[start, end],
            value=0.150,
        )
        apply_dimension(sketch, direct, 0.150)
        self.assertAlmostEqual(dimension_value(sketch, direct), 0.150)

    def test_zero_direction_distance_is_rejected_without_uuid_change(self):
        sketch = SketchFeature.on_plane("Zero", "XY")
        first = SketchLine(x1=0.0, y1=0.0, x2=0.0, y2=0.0)
        second = SketchLine(x1=0.0, y1=0.0, x2=0.0, y2=0.0)
        sketch.entities.extend((first, second))
        dimension = SketchDimension(
            dimension_type=DISTANCE,
            entity_refs=[self._ref(sketch, first, "START"), self._ref(sketch, second, "START")],
            value=0.2,
        )
        original = (second.x1, second.y1, second.id)
        with self.assertRaises(DimensionError):
            apply_dimension(sketch, dimension, 0.2)
        self.assertEqual((second.x1, second.y1, second.id), original)

    def test_circle_radius_and_diameter(self):
        sketch = SketchFeature.on_plane("Circle", "XY")
        circle = SketchCircle(cx=0.010, cy=-0.005, radius=0.005)
        sketch.entities.append(circle)
        radius = SketchDimension(
            dimension_type=RADIUS,
            entity_refs=[self._ref(sketch, circle)],
            value=0.008,
        )
        apply_dimension(sketch, radius, 0.008)
        self.assertAlmostEqual(circle.radius, 0.008)
        diameter = SketchDimension(
            dimension_type=DIAMETER,
            entity_refs=[self._ref(sketch, circle)],
            value=0.020,
        )
        apply_dimension(sketch, diameter, 0.020)
        self.assertAlmostEqual(circle.radius, 0.010)

    def test_conflicts_missing_references_and_cascade_cleanup(self):
        sketch, line, _other = self._line_sketch()
        first = SketchDimension(
            dimension_type=LENGTH,
            entity_refs=[self._ref(sketch, line)],
            value=0.1,
        )
        sketch.dimensions.append(first)
        duplicate = SketchDimension(
            dimension_type=LENGTH,
            entity_refs=[self._ref(sketch, line)],
            value=0.2,
        )
        with self.assertRaises(DimensionError):
            validate_dimension_conflicts(sketch, duplicate)
        missing = SketchDimension(
            dimension_type=LENGTH,
            entity_refs=[SketchEntityReference(sketch.id, "deleted-entity", "ENTITY")],
            value=0.1,
        )
        sketch.dimensions.append(missing)
        result = SketchSolver().solve(sketch)
        self.assertFalse(result.success)
        self.assertEqual(missing.status, "INVALID")
        self.assertEqual(remove_dimensions_for_entity(sketch, line.id), 1)
        self.assertEqual(len(sketch.dimensions), 1)

    def test_serialization_contains_semantic_refs_and_round_trips(self):
        sketch, line, _other = self._line_sketch()
        sketch.dimensions.append(
            SketchDimension(
                dimension_type=LENGTH,
                entity_refs=[self._ref(sketch, line)],
                value=0.1,
                label_position=(0.0, 0.02),
            )
        )
        document = CadDocument(parts=[Part(features=[sketch])], active_part_id=None)
        document.active_part_id = document.parts[0].id
        payload = document_to_dict(document)
        serialized = str(payload)
        self.assertIn("entity_refs", serialized)
        self.assertIn(sketch.id, serialized)
        self.assertIn(line.id, serialized)
        self.assertNotIn("mesh_edge_index", serialized)
        restored = document_from_dict(payload)
        restored_sketch = restored.parts[0].features[0]
        self.assertEqual(restored_sketch.entities[0].id, line.id)
        self.assertEqual(restored_sketch.dimensions[0].entity_refs[0].entity_id, line.id)
        self.assertEqual(restored_sketch.dimensions[0].label_position, (0.0, 0.02))

    def test_solver_accepts_valid_driving_dimension(self):
        sketch, line, _other = self._line_sketch()
        sketch.dimensions.append(
            SketchDimension(
                dimension_type=LENGTH,
                entity_refs=[self._ref(sketch, line)],
                value=0.1,
            )
        )
        result = SketchSolver().solve(sketch)
        self.assertTrue(result.success, result.message)


if __name__ == "__main__":
    unittest.main()
