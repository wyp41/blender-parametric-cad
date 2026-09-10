"""Run in a fresh Blender process after the M8.1 save validation script."""

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


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    if not hasattr(bpy.types.Scene, "parametric_cad_document"):
        blender_parametric_cad.register()

    document = load_document_from_scene(bpy.context.scene)
    part = document.active_part
    _check(part is not None, "No active Part Studio after opening the saved file.")
    result = rebuild_part(bpy.context.scene, part.id)
    _check(result.success, "Rebuild after opening the saved file failed.")
    restored = load_document_from_scene(bpy.context.scene)
    restored_part = restored.get_part(part.id)
    _check(restored_part is not None, "Part Studio was not restored.")
    _check(
        all(
            feature.status == "OK"
            for feature in restored_part.features
            if feature.feature_type in {"CHAMFER", "FILLET"}
        ),
        "An edge feature did not resolve after reopening.",
    )

    result_objects = [
        item
        for item in bpy.data.objects
        if item.get("cad_generated") and item.get("cad_part_id") == part.id
    ]
    _check(len(result_objects) == 1, "Reopen produced an incorrect number of result objects.")
    candidates = get_edge_candidates(result_objects[0])
    _check(candidates, "Runtime edge candidate cache was not rebuilt after reopening.")

    raw = getattr(bpy.context.scene, "parametric_cad_document", "")
    json.loads(raw)
    for forbidden in ("mesh_edge_index", "edge_index", "bmesh_edge", "candidate_id"):
        _check(forbidden not in raw, f"Runtime edge field {forbidden!r} was serialized.")
    print("BLENDER_PARAMETRIC_CAD_M8_1_RELOAD_OK")


main()
