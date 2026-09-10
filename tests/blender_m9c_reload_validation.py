"""M9C save/reload validation through MCP inspection handlers."""

from __future__ import annotations

import sys
from pathlib import Path

import bpy

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from blender_parametric_cad.mcp.blender_worker import BlenderCadWorker


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


worker = BlenderCadWorker()
history = worker.handle("cad_get_history", {})
part_id = history["part_id"]
sketch = next(item for item in history["features"] if item["name"] == "Base")
inspection = worker.handle("cad_get_sketch", {"sketch_id": sketch["id"]})
_check(inspection["solver_status"] == "SOLVED", inspection["solver_message"])
_check(inspection["constraints"], "M9C constraints were not restored.")
_check(inspection["dimensions"], "M9C dimensions were not restored.")
edges = worker.handle("cad_get_edges", {"part_id": part_id})
_check(edges["edges"], "Runtime semantic edge cache was not rebuilt.")
validation = worker.handle("cad_validate_document", {})
_check(validation["valid"], str(validation))
print("BLENDER_PARAMETRIC_CAD_M9C_RELOAD_OK")
