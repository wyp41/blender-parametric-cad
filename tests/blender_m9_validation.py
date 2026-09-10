"""Blender 5.1 M9A/M9B integration validation.

This script exercises real Blender registration, document persistence, mesh
rebuilds, and a downstream M8 Chamfer while the driving dimensions live on
the Sketch.  GUI hover/click is validated separately because it needs a real
3D View event stream.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import bpy

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import blender_parametric_cad
from blender_parametric_cad.blender.adapter import (
    load_document_from_scene,
    rebuild_part,
    save_document_to_scene,
)
from blender_parametric_cad.blender.viewport.provenance import (
    clear_runtime_caches,
    get_edge_candidates,
)
from blender_parametric_cad.core.document import CadDocument
from blender_parametric_cad.core.part import Part
from blender_parametric_cad.core.references import SketchEntityReference
from blender_parametric_cad.features.chamfer import ChamferFeature
from blender_parametric_cad.features.extrude import ExtrudeFeature
from blender_parametric_cad.sketch.dimensions import (
    DIAMETER,
    LENGTH,
    RADIUS,
    SketchDimension,
    apply_dimension,
    dimension_value,
)
from blender_parametric_cad.sketch.entities import SketchCircle, SketchLine
from blender_parametric_cad.sketch.sketch import SketchFeature


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _enter_temporary_scene():
    """Run validation in an isolated Scene, leaving the user's scene intact."""

    original_scene = bpy.context.scene
    if getattr(bpy.context, "window", None) is None:
        # Background Blender has no window to switch.  Its factory-startup
        # scene is already isolated from the user's interactive file.
        clear_runtime_caches()
        return None, original_scene
    temporary_scene = bpy.data.scenes.new("CAD_M9_Validation_Temporary")
    bpy.context.window.scene = temporary_scene
    clear_runtime_caches()
    return original_scene, temporary_scene


def _leave_temporary_scene(original_scene, temporary_scene, part_id: str) -> None:
    for obj in list(bpy.data.objects):
        if obj.get("cad_generated") and obj.get("cad_part_id") == part_id:
            mesh = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
    if original_scene is not None and getattr(bpy.context, "window", None) is not None:
        bpy.context.window.scene = original_scene
    if temporary_scene is not original_scene:
        bpy.data.scenes.remove(temporary_scene)
    clear_runtime_caches()


def _rectangle() -> list[SketchLine]:
    return [
        SketchLine(x1=0.0, y1=0.0, x2=0.080, y2=0.0),
        SketchLine(x1=0.080, y1=0.0, x2=0.080, y2=0.050),
        SketchLine(x1=0.080, y1=0.050, x2=0.0, y2=0.050),
        SketchLine(x1=0.0, y1=0.050, x2=0.0, y2=0.0),
    ]


def _result_object(part_id: str):
    return next(
        obj
        for obj in bpy.data.objects
        if obj.get("cad_generated") and obj.get("cad_part_id") == part_id
    )


def _rebuild(document: CadDocument, part_id: str):
    save_document_to_scene(bpy.context.scene, document)
    result = rebuild_part(bpy.context.scene, part_id)
    _check(result.success, "; ".join(error.message for error in result.errors))
    return load_document_from_scene(bpy.context.scene)


def main() -> None:
    original_scene, temporary_scene = _enter_temporary_scene()
    part_id = ""
    try:
        if not hasattr(bpy.types.Scene, "parametric_cad_document"):
            blender_parametric_cad.register()
        _check(hasattr(bpy.types, "PARAMETRIC_CAD_OT_add_dimension"), "Dimension operator did not register.")
        _check(hasattr(bpy.types.Scene, "parametric_cad_ui"), "CAD UI state did not register.")

        document = CadDocument()
        part = Part(name="M9 Part")
        part_id = part.id
        sketch = SketchFeature.on_plane("Sketch001", "XY")
        sketch.entities = _rectangle()
        construction = SketchLine(
        x1=0.0,
        y1=-0.015,
        x2=0.080,
        y2=-0.015,
        construction=True,
        )
        circle = SketchCircle(cx=0.040, cy=0.025, radius=0.008, construction=True)
        sketch.entities.extend((construction, circle))
        length_dimension = SketchDimension(
        dimension_type=LENGTH,
        entity_refs=[SketchEntityReference(sketch.id, construction.id, "ENTITY")],
        value=0.080,
        )
        radius_dimension = SketchDimension(
        dimension_type=RADIUS,
        entity_refs=[SketchEntityReference(sketch.id, circle.id, "ENTITY")],
        value=0.008,
        )
        sketch.dimensions.extend((length_dimension, radius_dimension))
        extrude = ExtrudeFeature(
        name="Extrude001",
        sketch_id=sketch.id,
        distance=0.020,
        operation="NEW",
        )
        part.features.extend((sketch, extrude))
        document.add_part(part)
        document = _rebuild(document, part.id)
        part = document.active_part
        sketch = part.features[0]
        _check(all(dimension.status == "OK" for dimension in sketch.dimensions), "Valid dimensions were not accepted by Blender evaluator.")
        original_line_id = sketch.entities[4].id
        apply_dimension(sketch, sketch.dimensions[0], 0.100)
        _check(sketch.entities[4].id == original_line_id, "Driving dimension changed the entity UUID.")
        _check(abs(dimension_value(sketch, sketch.dimensions[0]) - 0.100) < 1e-9, "Length edit did not apply.")
        apply_dimension(sketch, sketch.dimensions[1], 0.010)
        _check(abs(sketch.entities[5].radius - 0.010) < 1e-9, "Radius edit did not apply.")
        document = _rebuild(document, part.id)
        part = document.active_part
        _check(part.features[1].status == "OK", "Upstream dimension edit blocked Extrude.")

        result_object = _result_object(part.id)
        top = [
        candidate
        for candidate in get_edge_candidates(result_object).values()
        if candidate.semantic_reference is not None
        and all(abs(point[2] - 0.020) < 1e-8 for point in (candidate.start, candidate.end))
        ]
        _check(top, "No real Blender top edge candidate was generated.")
        chamfer = ChamferFeature(
        name="Chamfer001",
        edge_references=[top[0].semantic_reference],
        distance=0.002,
        )
        part.add_feature(chamfer)
        document = _rebuild(document, part.id)
        part = document.active_part
        _check(part.features[-1].status == "OK", "Downstream Chamfer did not rebuild after dimension edit.")

        raw = bpy.context.scene.parametric_cad_document
        json.loads(raw)
        _check("mesh_edge_index" not in raw and "edge_index" not in raw, "Runtime mesh index leaked into CAD JSON.")
        path = str(Path(tempfile.gettempdir()) / "blender_parametric_cad_m9.blend")
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
        print(f"M9 dimensions + downstream Chamfer: OK ({path})")
        print("BLENDER_PARAMETRIC_CAD_M9_VALIDATION_OK")
    finally:
        _leave_temporary_scene(original_scene, temporary_scene, part_id)


main()
