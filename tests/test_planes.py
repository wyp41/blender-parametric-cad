from __future__ import annotations

import unittest

from blender_parametric_cad.core.document import CadDocument
from blender_parametric_cad.core.part import Part
from blender_parametric_cad.core.serialization import migrate_document_data
from blender_parametric_cad.features.extrude import ExtrudeFeature
from blender_parametric_cad.sketch.plane import resolve_sketch_plane_from_history
from blender_parametric_cad.sketch.sketch import SketchFeature

from .helpers import rectangle_sketch


class SemanticPlaneTests(unittest.TestCase):
    def test_datum_plane_reference_round_trip(self) -> None:
        sketch = SketchFeature.on_plane("Sketch001", "XZ")
        restored = CadDocument.from_dict(
            CadDocument(parts=[Part(features=[sketch])]).to_dict()
        ).parts[0].features[0]
        self.assertEqual(restored.plane_reference.reference_type, "DATUM")
        self.assertEqual(restored.plane_reference.datum_plane, "XZ")

    def test_end_plane_moves_with_extrusion_distance(self) -> None:
        base = rectangle_sketch()
        extrude = ExtrudeFeature(name="Extrude001", sketch_id=base.id, distance=0.02)
        second = SketchFeature.on_feature_plane("Sketch002", extrude.id)
        part = Part(features=[base, extrude, second])

        first = resolve_sketch_plane_from_history(part, second.id)
        extrude.distance = 0.04
        moved = resolve_sketch_plane_from_history(part, second.id)

        self.assertEqual(first.origin, (0.0, 0.0, 0.02))
        self.assertEqual(moved.origin, (0.0, 0.0, 0.04))
        self.assertEqual(second.dependencies, [extrude.id])


class SchemaMigrationTests(unittest.TestCase):
    def test_schema_v1_migrates_to_v2(self) -> None:
        legacy = {
            "schema_version": 1,
            "active_part_id": "part-id",
            "parts": [
                {
                    "id": "part-id",
                    "name": "Part001",
                    "features": [
                        {
                            "id": "sketch-id",
                            "name": "Sketch001",
                            "feature_type": "SKETCH",
                            "plane_type": "XY",
                            "origin": [0, 0, 0],
                            "x_axis": [1, 0, 0],
                            "y_axis": [0, 1, 0],
                            "entities": [],
                        },
                        {
                            "id": "extrude-id",
                            "name": "Extrude001",
                            "feature_type": "EXTRUDE",
                            "sketch_id": "sketch-id",
                            "distance": 0.02,
                            "direction": 1,
                            "operation": "NEW",
                        },
                    ],
                }
            ],
        }

        migrated = migrate_document_data(legacy)
        document = CadDocument.from_dict(legacy)

        self.assertEqual(migrated["schema_version"], 2)
        self.assertEqual(
            migrated["parts"][0]["features"][0]["plane_reference"]["datum_plane"],
            "XY",
        )
        self.assertEqual(document.schema_version, 2)
        self.assertEqual(document.parts[0].features[1].dependencies, ["sketch-id"])
        self.assertIsNone(document.parts[0].rollback_index)


if __name__ == "__main__":
    unittest.main()
