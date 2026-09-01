from __future__ import annotations

import unittest

from blender_parametric_cad.core.document import CadDocument
from blender_parametric_cad.core.part import Part, delete_feature, get_recursive_dependents
from blender_parametric_cad.core.serialization import dumps, loads
from blender_parametric_cad.features.extrude import ExtrudeFeature
from blender_parametric_cad.sketch.entities import SketchCircle
from blender_parametric_cad.sketch.sketch import SketchFeature

from .helpers import rectangle_sketch


def feature_chain():
    base = rectangle_sketch()
    extrude = ExtrudeFeature(name="Extrude001", sketch_id=base.id, distance=0.04)
    hole = SketchFeature.on_feature_plane("Sketch002", extrude.id)
    hole.entities = [SketchCircle(cx=0.04, cy=0.025, radius=0.005)]
    cut = ExtrudeFeature(
        name="Cut001",
        sketch_id=hole.id,
        operation="CUT",
        depth_mode="THROUGH_ALL",
        dependencies=[hole.id, extrude.id],
    )
    return Part(features=[base, extrude, hole, cut]), base, extrude, hole, cut


class PartStudioManagementTests(unittest.TestCase):
    def test_active_part_switching_and_lookup(self) -> None:
        first, second = Part(name="Part Studio 1"), Part(name="Part Studio 2")
        document = CadDocument(parts=[first, second], active_part_id=second.id)

        self.assertIs(document.get_active_part(), second)
        self.assertIs(document.set_active_part(first.id), first)
        self.assertIs(document.active_part, first)
        with self.assertRaises(ValueError):
            document.set_active_part("missing")

    def test_part_rename_changes_only_display_name(self) -> None:
        part, _base, extrude, _hole, _cut = feature_chain()
        original_id, dependency = part.id, extrude.sketch_id

        part.name = "Bracket"

        self.assertEqual(part.id, original_id)
        self.assertEqual(extrude.sketch_id, dependency)

    def test_active_selection_after_part_delete_is_deterministic(self) -> None:
        first, second, third = Part(), Part(), Part()
        document = CadDocument(parts=[first, second, third], active_part_id=second.id)

        self.assertIs(document.remove_part(second.id), second)
        self.assertEqual(document.active_part_id, first.id)
        document.set_active_part(first.id)
        document.remove_part(first.id)
        self.assertEqual(document.active_part_id, third.id)
        document.remove_part(third.id)
        self.assertIsNone(document.active_part_id)

    def test_deleting_inactive_part_preserves_active_selection(self) -> None:
        first, second = Part(), Part()
        document = CadDocument(parts=[first, second], active_part_id=first.id)

        document.remove_part(second.id)

        self.assertIs(document.active_part, first)

    def test_duplicate_feature_names_are_scoped_by_part_uuid(self) -> None:
        first_sketch, second_sketch = rectangle_sketch(), rectangle_sketch(0.03, 0.03)
        first = Part(features=[first_sketch])
        second = Part(features=[second_sketch])

        self.assertEqual(first_sketch.name, second_sketch.name)
        self.assertNotEqual(first_sketch.id, second_sketch.id)
        self.assertIs(first.get_feature(first_sketch.id), first_sketch)
        self.assertIsNone(first.get_feature(second_sketch.id))

    def test_part_studio_isolation(self) -> None:
        first_sketch, second_sketch = rectangle_sketch(), rectangle_sketch(0.03, 0.03)
        first_extrude = ExtrudeFeature(sketch_id=first_sketch.id, distance=0.04)
        second_extrude = ExtrudeFeature(sketch_id=second_sketch.id, distance=0.015)
        first = Part(features=[first_sketch, first_extrude])
        second = Part(features=[second_sketch, second_extrude])
        document = CadDocument(parts=[first, second], active_part_id=first.id)

        document.active_part.features[1].distance = 0.03
        delete_feature(first, first_extrude.id)

        self.assertEqual(second_extrude.distance, 0.015)
        self.assertEqual(len(second.features), 2)

    def test_multi_part_serialization_round_trip(self) -> None:
        first_sketch, second_sketch = rectangle_sketch(), rectangle_sketch(0.03, 0.03)
        first = Part(
            name="Bracket",
            features=[first_sketch, ExtrudeFeature(sketch_id=first_sketch.id, distance=0.04)],
        )
        second = Part(
            name="Pin",
            features=[second_sketch, ExtrudeFeature(sketch_id=second_sketch.id, distance=0.015)],
        )
        document = CadDocument(parts=[first, second], active_part_id=second.id)

        restored = loads(dumps(document))

        self.assertEqual(restored.to_dict(), document.to_dict())
        self.assertEqual(restored.active_part_id, second.id)
        self.assertEqual(restored.parts[0].features[1].distance, 0.04)
        self.assertEqual(restored.parts[1].features[1].distance, 0.015)


class FeatureManagementTests(unittest.TestCase):
    def test_recursive_dependents_use_uuid_dependencies(self) -> None:
        part, base, extrude, hole, cut = feature_chain()

        self.assertEqual(get_recursive_dependents(part, hole.id), [cut.id])
        self.assertEqual(get_recursive_dependents(part, extrude.id), [hole.id, cut.id])
        self.assertEqual(
            get_recursive_dependents(part, base.id), [extrude.id, hole.id, cut.id]
        )

    def test_leaf_and_unused_sketch_delete(self) -> None:
        part, _base, _extrude, hole, cut = feature_chain()

        self.assertEqual(delete_feature(part, cut.id), [cut])
        self.assertEqual(delete_feature(part, hole.id), [hole])
        self.assertEqual(len(part.features), 2)

    def test_cascade_and_deep_cascade_delete(self) -> None:
        part, _base, extrude, hole, cut = feature_chain()

        self.assertEqual(delete_feature(part, hole.id), [hole, cut])
        self.assertEqual(len(part.features), 2)

        part, base, extrude, hole, cut = feature_chain()
        self.assertEqual(delete_feature(part, extrude.id), [extrude, hole, cut])
        self.assertEqual(part.features, [base])

    def test_root_delete_removes_entire_chain_and_resets_rollback(self) -> None:
        part, base, extrude, hole, cut = feature_chain()
        part.rollback_index = 3

        self.assertEqual(delete_feature(part, base.id), [base, extrude, hole, cut])
        self.assertEqual(part.features, [])
        self.assertIsNone(part.rollback_index)

    def test_suppressed_feature_remains_structural_and_deletable(self) -> None:
        part, _base, extrude, hole, cut = feature_chain()
        hole.suppressed = True
        cut.suppressed = True

        self.assertEqual(get_recursive_dependents(part, extrude.id), [hole.id, cut.id])
        self.assertEqual(delete_feature(part, hole.id), [hole, cut])

    def test_feature_rename_preserves_uuid_dependency_and_round_trip(self) -> None:
        part, base, extrude, _hole, _cut = feature_chain()
        base_id = base.id

        base.name = "Base Sketch"
        restored = loads(dumps(CadDocument(parts=[part], active_part_id=part.id)))
        restored_part = restored.active_part

        self.assertEqual(restored_part.get_feature(base_id).name, "Base Sketch")
        self.assertEqual(restored_part.get_feature(extrude.id).sketch_id, base_id)
        self.assertEqual(restored_part.get_feature(extrude.id).dependencies, [base_id])


if __name__ == "__main__":
    unittest.main()
