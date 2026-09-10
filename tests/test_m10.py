from __future__ import annotations

import json
import unittest

from blender_parametric_cad.core.serialization import feature_from_dict, feature_to_dict
from blender_parametric_cad.mcp.protocol import TOOL_DEFINITIONS
from blender_parametric_cad.sketch.numeric import (
    rectangle_parameters_by_id,
    set_rectangle,
)
from blender_parametric_cad.sketch.sketch import SketchFeature


class M10RectangleTests(unittest.TestCase):
    def test_rectangle_metadata_round_trips_without_mesh_indices(self) -> None:
        sketch = SketchFeature.on_plane("Sketch", "XY")
        set_rectangle(sketch, 0.0, 0.0, 0.08, 0.05)
        rectangle = sketch.rectangles[0]
        self.assertEqual(rectangle_parameters_by_id(sketch, rectangle.id), (0.0, 0.0, 0.08, 0.05))

        data = feature_to_dict(sketch)
        encoded = json.dumps(data)
        self.assertNotIn("mesh_edge_index", encoded)
        restored = feature_from_dict(data)
        self.assertEqual(restored.rectangles[0].id, rectangle.id)
        self.assertEqual(restored.rectangles[0].entity_ids, rectangle.entity_ids)

    def test_m10_tools_are_discoverable(self) -> None:
        names = {item["name"] for item in TOOL_DEFINITIONS}
        self.assertTrue(
            {
                "cad_sketch_update_rectangle",
                "cad_list_references",
                "cad_inspect_geometry",
                "cad_get_document",
                "cad_get_part_studio",
                "cad_get_feature",
            }.issubset(names)
        )


if __name__ == "__main__":
    unittest.main()
