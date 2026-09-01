from __future__ import annotations

import unittest

from blender_parametric_cad.core.document import CadDocument


class SerializationValidationTests(unittest.TestCase):
    def test_rejects_unknown_schema(self) -> None:
        with self.assertRaises(ValueError):
            CadDocument.from_dict({"schema_version": 99, "parts": []})


if __name__ == "__main__":
    unittest.main()
