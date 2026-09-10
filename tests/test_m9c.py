from __future__ import annotations

import unittest

from blender_parametric_cad.core.document import CadDocument
from blender_parametric_cad.core.part import Part
from blender_parametric_cad.core.references import SketchEntityReference
from blender_parametric_cad.core.serialization import document_from_dict, document_to_dict
from blender_parametric_cad.sketch.constraints import (
    SketchConstraint,
    remove_constraints_for_entity,
)
from blender_parametric_cad.sketch.dimensions import (
    LENGTH,
    SketchDimension,
    remove_dimensions_for_entity,
)
from blender_parametric_cad.sketch.entities import SketchCircle, SketchLine
from blender_parametric_cad.sketch.sketch import SketchFeature
from blender_parametric_cad.sketch.solver import CONFLICT, INVALID_REFERENCE, SketchSolver


class SketchConstraintTests(unittest.TestCase):
    @staticmethod
    def ref(sketch, entity, sub="ENTITY"):
        return SketchEntityReference(sketch.id, entity.id, sub)

    def test_horizontal_vertical_and_coincident(self):
        sketch = SketchFeature.on_plane("Constraints", "XY")
        first = SketchLine(x1=0.0, y1=0.0, x2=0.080, y2=0.012)
        second = SketchLine(x1=0.080, y1=0.020, x2=0.080, y2=0.060)
        sketch.entities.extend((first, second))
        sketch.constraints.extend(
            (
                SketchConstraint(constraint_type="HORIZONTAL", entity_refs=[self.ref(sketch, first)]),
                SketchConstraint(constraint_type="VERTICAL", entity_refs=[self.ref(sketch, second)]),
                SketchConstraint(
                    constraint_type="COINCIDENT",
                    entity_refs=[self.ref(sketch, first, "END"), self.ref(sketch, second, "START")],
                ),
            )
        )
        result = SketchSolver().solve(sketch)
        self.assertTrue(result.success, result.message)
        self.assertEqual(result.status, "SOLVED")
        self.assertAlmostEqual(first.y1, first.y2)
        self.assertAlmostEqual(second.x1, second.x2)
        self.assertAlmostEqual(first.x2, second.x1)
        self.assertAlmostEqual(first.y2, second.y1)

    def test_parallel_perpendicular_and_equal(self):
        sketch = SketchFeature.on_plane("Directions", "XY")
        first = SketchLine(x1=0.0, y1=0.0, x2=0.080, y2=0.0)
        second = SketchLine(x1=0.0, y1=0.020, x2=0.030, y2=0.040)
        third = SketchLine(x1=0.0, y1=0.050, x2=0.020, y2=0.070)
        sketch.entities.extend((first, second, third))
        sketch.constraints.extend(
            (
                SketchConstraint(constraint_type="PARALLEL", entity_refs=[self.ref(sketch, first), self.ref(sketch, second)]),
                SketchConstraint(constraint_type="PERPENDICULAR", entity_refs=[self.ref(sketch, first), self.ref(sketch, third)]),
                SketchConstraint(constraint_type="EQUAL", entity_refs=[self.ref(sketch, first), self.ref(sketch, second)]),
            )
        )
        result = SketchSolver().solve(sketch)
        self.assertTrue(result.success, result.message)
        self.assertAlmostEqual(second.y2, second.y1)
        self.assertAlmostEqual(third.x2, third.x1)
        self.assertAlmostEqual(first.x2 - first.x1, second.x2 - second.x1)

    def test_equal_circles_and_dimensions_join_solver(self):
        sketch = SketchFeature.on_plane("Circles", "XY")
        first = SketchCircle(cx=0.0, cy=0.0, radius=0.005)
        second = SketchCircle(cx=0.020, cy=0.0, radius=0.008)
        line = SketchLine(x1=0.0, y1=0.0, x2=0.080, y2=0.0)
        sketch.entities.extend((first, second, line))
        sketch.constraints.append(
            SketchConstraint(constraint_type="EQUAL", entity_refs=[self.ref(sketch, first), self.ref(sketch, second)])
        )
        sketch.dimensions.append(
            SketchDimension(dimension_type=LENGTH, entity_refs=[self.ref(sketch, line)], value=0.1)
        )
        result = SketchSolver().solve(sketch)
        self.assertTrue(result.success, result.message)
        self.assertAlmostEqual(first.radius, second.radius)
        self.assertAlmostEqual(line.x2 - line.x1, 0.1)

    def test_conflict_is_transactional(self):
        sketch = SketchFeature.on_plane("Conflict", "XY")
        line = SketchLine(x1=0.0, y1=0.0, x2=0.080, y2=0.020)
        sketch.entities.append(line)
        sketch.constraints.extend(
            (
                SketchConstraint(constraint_type="HORIZONTAL", entity_refs=[self.ref(sketch, line)]),
                SketchConstraint(constraint_type="VERTICAL", entity_refs=[self.ref(sketch, line)]),
            )
        )
        original = (line.x1, line.y1, line.x2, line.y2)
        result = SketchSolver().solve(sketch)
        self.assertFalse(result.success)
        self.assertEqual(result.status, CONFLICT)
        self.assertEqual((line.x1, line.y1, line.x2, line.y2), original)

    def test_invalid_reference_and_delete_cleanup(self):
        sketch = SketchFeature.on_plane("Invalid", "XY")
        line = SketchLine(x1=0.0, y1=0.0, x2=0.050, y2=0.0)
        sketch.entities.append(line)
        sketch.constraints.append(
            SketchConstraint(
                constraint_type="HORIZONTAL",
                entity_refs=[SketchEntityReference(sketch.id, "missing", "ENTITY")],
            )
        )
        result = SketchSolver().solve(sketch)
        self.assertFalse(result.success)
        self.assertEqual(result.status, INVALID_REFERENCE)

    def test_constraint_serialization(self):
        sketch = SketchFeature.on_plane("Persist", "XY")
        first = SketchLine(x1=0.0, y1=0.0, x2=0.050, y2=0.0)
        second = SketchLine(x1=0.050, y1=0.0, x2=0.050, y2=0.030)
        sketch.entities.extend((first, second))
        constraint = SketchConstraint(
            constraint_type="COINCIDENT",
            entity_refs=[self.ref(sketch, first, "END"), self.ref(sketch, second, "START")],
        )
        sketch.constraints.append(constraint)
        document = CadDocument(parts=[Part(features=[sketch])])
        document.active_part_id = document.parts[0].id
        restored = document_from_dict(document_to_dict(document))
        restored_sketch = restored.parts[0].features[0]
        self.assertEqual(restored_sketch.constraints[0].id, constraint.id)
        self.assertEqual(restored_sketch.constraints[0].entity_refs[0].entity_id, first.id)
        self.assertEqual(restored_sketch.constraints[0].entity_refs[0].sub_element, "END")

    def test_entity_deletion_cleanup_removes_dependent_equations(self):
        sketch = SketchFeature.on_plane("Cleanup", "XY")
        first = SketchLine(x1=0.0, y1=0.0, x2=0.050, y2=0.0)
        second = SketchLine(x1=0.050, y1=0.0, x2=0.050, y2=0.030)
        sketch.entities.extend((first, second))
        sketch.constraints.append(
            SketchConstraint(
                constraint_type="COINCIDENT",
                entity_refs=[self.ref(sketch, first, "END"), self.ref(sketch, second, "START")],
            )
        )
        sketch.dimensions.append(
            SketchDimension(
                dimension_type=LENGTH,
                entity_refs=[self.ref(sketch, first)],
                value=0.050,
            )
        )
        sketch.entities.remove(first)
        self.assertEqual(remove_constraints_for_entity(sketch, first.id), 1)
        self.assertEqual(remove_dimensions_for_entity(sketch, first.id), 1)
        self.assertEqual(SketchSolver().solve(sketch).status, "SOLVED")


if __name__ == "__main__":
    unittest.main()
