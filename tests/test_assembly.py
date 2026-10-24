"""Blender-independent linked Assembly model and schema migration checks."""

import ast
from copy import deepcopy
from math import pi
from pathlib import Path
import unittest

from blender_parametric_cad.core.assembly import Assembly, AssemblyInstance, PartInUseError
from blender_parametric_cad.core.document import CadDocument
from blender_parametric_cad.core.part import Part
from blender_parametric_cad.core.serialization import dumps, loads, migrate_document_data
from blender_parametric_cad.core.transform import Transform, transform_point
from blender_parametric_cad.tests.helpers import rectangle_sketch
from blender_parametric_cad.features.extrude import ExtrudeFeature


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        self.document = CadDocument()
        self.part = Part(name="Guide")
        self.document.add_part(self.part)
        self.assembly = self.document.add_assembly(Assembly())

    def add_instance(self, **kwargs):
        return self.document.add_instance(self.assembly.id, AssemblyInstance(part_studio_id=self.part.id, **kwargs))

    def test_creation_and_deletion_leave_source_history(self):
        self.add_instance()
        self.assertIs(self.document.get_assembly(self.assembly.id), self.assembly)
        self.assertIs(self.document.remove_assembly(self.assembly.id), self.assembly)
        self.assertIs(self.document.get_part(self.part.id), self.part)
        self.assertIsNone(self.document.get_assembly(self.assembly.id))

    def test_multiple_unique_placements_share_source(self):
        left = self.add_instance(transform=Transform((-0.05, 0, 0)).matrix)
        right = self.add_instance(transform=Transform((0.05, 0, 0), (0, 0, pi)).matrix)
        self.assertNotEqual(left.id, right.id)
        self.assertEqual(left.part_studio_id, right.part_studio_id)
        self.assertEqual(transform_point(left.transform, (0, 0, 0)), (-0.05, 0, 0))
        self.assertEqual(transform_point(right.transform, (0, 0, 0)), (0.05, 0, 0))
        self.assertEqual(self.part.features, [])
        self.assertEqual(len(self.document.parts), 1)

    def test_suppression_and_transform_json_round_trip(self):
        instance = self.add_instance(suppressed=True, transform=Transform((.02, .03, .04), (.2, .3, .4)).matrix)
        restored = loads(dumps(self.document))
        self.assertEqual(restored.schema_version, 3)
        self.assertEqual(restored.to_dict(), self.document.to_dict())
        self.assertTrue(restored.get_instance(self.assembly.id, instance.id).suppressed)
        self.assertEqual(restored.get_instance(self.assembly.id, instance.id).transform, instance.transform)

    def test_remove_instance_does_not_remove_source_or_other_placements(self):
        first, second = self.add_instance(), self.add_instance()
        self.assertIs(self.document.remove_instance(self.assembly.id, first.id), first)
        self.assertIs(self.document.get_instance(self.assembly.id, second.id), second)
        self.assertIs(self.document.get_part(self.part.id), self.part)

    def test_unknown_source_and_assembly_rejected(self):
        with self.assertRaisesRegex(ValueError, "source Part Studio"):
            self.document.add_instance(self.assembly.id, AssemblyInstance(part_studio_id="missing"))
        with self.assertRaisesRegex(ValueError, "Unknown Assembly"):
            self.document.add_instance("missing", AssemblyInstance(part_studio_id=self.part.id))

    def test_referenced_part_deletion_reports_all_dependencies(self):
        first, second = self.add_instance(), self.add_instance(suppressed=True)
        with self.assertRaises(PartInUseError) as failure:
            self.document.remove_part(self.part.id)
        self.assertEqual(failure.exception.code, "PART_IN_USE")
        self.assertEqual(failure.exception.details["references"], [
            {"assembly_id": self.assembly.id, "instance_id": item.id} for item in (first, second)
        ])
        self.document.remove_assembly(self.assembly.id)
        self.assertIs(self.document.remove_part(self.part.id), self.part)

    def test_duplicate_instance_and_assembly_ids_rejected(self):
        instance = self.add_instance()
        with self.assertRaisesRegex(ValueError, "Duplicate Instance"):
            self.document.add_instance(self.assembly.id, deepcopy(instance))
        with self.assertRaisesRegex(ValueError, "Duplicate Assembly"):
            self.document.add_assembly(deepcopy(self.assembly))

    def test_v2_migration_preserves_complete_part_payload(self):
        sketch = rectangle_sketch(.02, .01)
        self.part.add_feature(sketch)
        self.part.add_feature(ExtrudeFeature(sketch_id=sketch.id, distance=.03))
        legacy = self.document.to_dict()
        legacy.pop("assemblies")
        legacy["schema_version"] = 2
        original = deepcopy(legacy)
        migrated = migrate_document_data(legacy)
        self.assertEqual(legacy, original)
        self.assertEqual(migrated["parts"], original["parts"])
        self.assertEqual(migrated["active_part_id"], self.part.id)
        self.assertEqual(migrated["assemblies"], [])
        self.assertEqual(CadDocument.from_dict(legacy).to_dict(), migrated)

    def test_invalid_transform_rejected(self):
        for matrix in (((1, 2),), Transform((0, 0, 0)).matrix[:3],
                       ((2, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))):
            with self.assertRaises(ValueError):
                AssemblyInstance(transform=matrix)

    def test_core_assembly_has_no_bpy_dependency(self):
        path = Path(__file__).parents[1] / "core" / "assembly.py"
        imports = [node for node in ast.walk(ast.parse(path.read_text())) if isinstance(node, (ast.Import, ast.ImportFrom))]
        self.assertFalse(any(getattr(node, "module", "") == "bpy" or
                             any(alias.name == "bpy" for alias in node.names) for node in imports))


if __name__ == "__main__":
    unittest.main()
