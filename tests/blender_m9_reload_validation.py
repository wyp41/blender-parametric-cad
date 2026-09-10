"""Reload companion for the M9 Blender validation file."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import blender_parametric_cad
from blender_parametric_cad.blender.adapter import load_document_from_scene, rebuild_part
from blender_parametric_cad.blender.viewport.provenance import get_edge_candidates
from blender_parametric_cad.sketch.sketch import SketchFeature


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    if not hasattr(bpy.types.Scene, "parametric_cad_document"):
        blender_parametric_cad.register()
    document = load_document_from_scene(bpy.context.scene)
    part = document.active_part
    _check(part is not None, "M9 Part Studio did not reopen.")
    result = rebuild_part(bpy.context.scene, part.id)
    _check(result.success, "; ".join(error.message for error in result.errors))
    restored = load_document_from_scene(bpy.context.scene)
    part = restored.active_part
    sketch = next(feature for feature in part.features if isinstance(feature, SketchFeature))
    _check(len(sketch.dimensions) == 2, "Sketch dimensions were not restored.")
    _check(all(dimension.status == "OK" for dimension in sketch.dimensions), "A restored dimension is invalid.")
    _check(part.features[-1].status == "OK", "Downstream Chamfer did not resolve after reload.")
    result_object = next(
        obj
        for obj in bpy.data.objects
        if obj.get("cad_generated") and obj.get("cad_part_id") == part.id
    )
    _check(get_edge_candidates(result_object), "Runtime edge cache was not rebuilt after reload.")
    raw = bpy.context.scene.parametric_cad_document
    json.loads(raw)
    _check("mesh_edge_index" not in raw and "edge_index" not in raw, "Runtime index persisted after reload.")
    print("BLENDER_PARAMETRIC_CAD_M9_RELOAD_OK")


main()
