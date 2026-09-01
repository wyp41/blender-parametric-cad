from __future__ import annotations

import unittest

from blender_parametric_cad.features.extrude import ExtrudeFeature

from .helpers import rectangle_sketch


class ExtrudeFeatureTests(unittest.TestCase):
    def test_source_reference_uses_sketch_uuid(self) -> None:
        sketch = rectangle_sketch()
        extrude = ExtrudeFeature(name="Extrude001", sketch_id=sketch.id)
        self.assertEqual(extrude.sketch_id, sketch.id)
        self.assertNotEqual(extrude.sketch_id, sketch.name)


if __name__ == "__main__":
    unittest.main()
