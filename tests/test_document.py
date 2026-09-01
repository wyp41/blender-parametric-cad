from __future__ import annotations

import unittest

from blender_parametric_cad.core.document import CadDocument
from blender_parametric_cad.core.part import Part
from blender_parametric_cad.core.serialization import dumps, loads
from blender_parametric_cad.features.extrude import ExtrudeFeature

from .helpers import rectangle_sketch


class DocumentSerializationTests(unittest.TestCase):
    def test_round_trip_preserves_ids_and_parameters(self) -> None:
        part = Part(name="Part001")
        sketch = rectangle_sketch()
        extrude = ExtrudeFeature(name="Extrude001", sketch_id=sketch.id, distance=0.04)
        part.features.extend([sketch, extrude])
        document = CadDocument(parts=[part], active_part_id=part.id)

        restored = loads(dumps(document))

        self.assertEqual(document.to_dict(), restored.to_dict())
        self.assertEqual(restored.active_part_id, part.id)
        self.assertEqual(restored.parts[0].features[1].distance, 0.04)


if __name__ == "__main__":
    unittest.main()
