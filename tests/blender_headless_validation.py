"""Blender 5.1 M3 validation: END_PLANE, CUT, history controls, and persistence."""

from __future__ import annotations

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
from blender_parametric_cad.sketch.entities import SketchCircle, SketchLine
from blender_parametric_cad.sketch.plane import resolve_sketch_plane_from_history


def result_object():
    return next(item for item in bpy.data.objects if item.get("cad_generated"))


def assert_dimensions(expected):
    actual = sorted(result_object().dimensions)
    assert all(abs(value - target) < 1e-6 for value, target in zip(actual, sorted(expected))), actual


def ray_hits(x: float, y: float) -> bool:
    hit, _location, _normal, _index = result_object().ray_cast(
        (x, y, 0.1), (0.0, 0.0, -1.0), distance=0.2
    )
    return hit


def resize_rectangle(sketch, width: float, height: float) -> None:
    for entity in sketch.entities:
        if isinstance(entity, SketchLine):
            if entity.x1 > 0.0:
                entity.x1 = width
            if entity.x2 > 0.0:
                entity.x2 = width
            if entity.y1 > 0.0:
                entity.y1 = height
            if entity.y2 > 0.0:
                entity.y2 = height


blender_parametric_cad.register()
scene = bpy.context.scene
ui = scene.parametric_cad_ui

# Sketch001: 80 x 50 mm rectangle on XY.
bpy.ops.parametric_cad.new_part()
ui.new_sketch_reference = "DATUM|XY"
assert bpy.ops.parametric_cad.new_sketch() == {"FINISHED"}
document = load_document_from_scene(scene)
part = document.active_part
assert part is not None
base_sketch = part.features[0]
base_sketch.entities = [
    SketchLine(x1=0.0, y1=0.0, x2=0.080, y2=0.0),
    SketchLine(x1=0.080, y1=0.0, x2=0.080, y2=0.050),
    SketchLine(x1=0.080, y1=0.050, x2=0.0, y2=0.050),
    SketchLine(x1=0.0, y1=0.050, x2=0.0, y2=0.0),
]
save_document_to_scene(scene, document)
bpy.ops.parametric_cad.finish_sketch()

# Extrude001: 20 mm NEW/BLIND.
ui.extrude_distance_mm = 20.0
assert bpy.ops.parametric_cad.extrude() == {"FINISHED"}
document = load_document_from_scene(scene)
part = document.active_part
extrude = part.features[1]
assert_dimensions((0.080, 0.050, 0.020))

# Sketch002: centered diameter-10 circle on Extrude001.END_PLANE.
ui.new_sketch_reference = f"FEATURE|{extrude.id}|END_PLANE"
assert bpy.ops.parametric_cad.new_sketch() == {"FINISHED"}
document = load_document_from_scene(scene)
part = document.active_part
hole_sketch = part.features[2]
hole_sketch.entities = [SketchCircle(cx=0.040, cy=0.025, radius=0.005)]
save_document_to_scene(scene, document)
bpy.ops.parametric_cad.finish_sketch()

# Cut001: Through All.
assert bpy.ops.parametric_cad.cut() == {"FINISHED"}
document = load_document_from_scene(scene)
part = document.active_part
cut = part.features[3]
feature_ids = [feature.id for feature in part.features]
assert [feature.name for feature in part.features] == [
    "Sketch001",
    "Extrude001",
    "Sketch002",
    "Cut001",
]
assert_dimensions((0.080, 0.050, 0.020))
assert not ray_hits(0.040, 0.025)
assert ray_hits(0.010, 0.010)

# Edit Extrude001 to 40 mm: semantic plane and hole both propagate.
ui.active_feature_id = extrude.id
ui.extrude_distance_mm = 40.0
assert bpy.ops.parametric_cad.apply_extrude() == {"FINISHED"}
document = load_document_from_scene(scene)
part = document.active_part
resolved = resolve_sketch_plane_from_history(part, hole_sketch.id)
assert abs(resolved.origin[2] - 0.040) < 1e-9, resolved.origin
assert_dimensions((0.080, 0.050, 0.040))
assert not ray_hits(0.040, 0.025)

# Rollback and roll forward without deleting downstream features.
ui.active_feature_id = extrude.id
assert bpy.ops.parametric_cad.rollback_here() == {"FINISHED"}
assert ray_hits(0.040, 0.025)
rolled = load_document_from_scene(scene).active_part
assert len(rolled.features) == 4 and rolled.rollback_index == 1
assert rolled.features[2].status == "NOT_EVALUATED"
assert bpy.ops.parametric_cad.roll_forward() == {"FINISHED"}
assert not ray_hits(0.040, 0.025)

# Suppress and unsuppress Cut001.
ui.active_feature_id = cut.id
assert bpy.ops.parametric_cad.toggle_suppression() == {"FINISHED"}
assert ray_hits(0.040, 0.025)
assert load_document_from_scene(scene).active_part.features[3].suppressed
assert bpy.ops.parametric_cad.toggle_suppression() == {"FINISHED"}
assert not ray_hits(0.040, 0.025)

# Base sketch and cut-sketch parameter propagation.
document = load_document_from_scene(scene)
part = document.active_part
resize_rectangle(part.features[0], 0.100, 0.060)
part.features[2].entities[0].cx = 0.050
part.features[2].entities[0].cy = 0.030
assert max(max(line.x1, line.x2) for line in part.features[0].entities) == 0.100
assert max(max(line.y1, line.y2) for line in part.features[0].entities) == 0.060
save_document_to_scene(scene, document)
assert rebuild_part(scene).success
assert_dimensions((0.100, 0.060, 0.040))
assert not ray_hits(0.050, 0.030)

document = load_document_from_scene(scene)
part = document.active_part
part.features[2].entities[0].radius = 0.0075
save_document_to_scene(scene, document)
assert rebuild_part(scene).success
assert not ray_hits(0.056, 0.030)  # inside the new Ø15 hole, outside the old Ø10 hole
assert ray_hits(0.059, 0.030)

# Repeated rebuilds must leave one display object and no Boolean helpers.
stable_mesh_count = len(bpy.data.meshes)
for distance in (0.020, 0.040, 0.030, 0.050, 0.020):
    document = load_document_from_scene(scene)
    document.active_part.features[1].distance = distance
    save_document_to_scene(scene, document)
    assert rebuild_part(scene).success
    assert len([item for item in bpy.data.objects if item.get("cad_generated")]) == 1
    assert not [item for item in bpy.data.objects if item.name.startswith("CAD_Boolean_")]
    assert not [item for item in bpy.data.meshes if item.name.startswith("CAD_ThroughAll_Cutter")]
    assert len(bpy.data.meshes) == stable_mesh_count

# Restore the benchmark shape, persist rollback/suppression, then restore and edit.
document = load_document_from_scene(scene)
part = document.active_part
resize_rectangle(part.features[0], 0.080, 0.050)
part.features[1].distance = 0.040
circle = part.features[2].entities[0]
circle.cx, circle.cy, circle.radius = 0.040, 0.025, 0.005
part.rollback_index = 1
part.features[3].suppressed = True
save_document_to_scene(scene, document)
assert rebuild_part(scene).success

blend_path = str(Path(tempfile.gettempdir()) / "blender_parametric_cad_m3_validation.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend_path)
bpy.ops.wm.open_mainfile(filepath=blend_path)
restored = load_document_from_scene(bpy.context.scene)
restored_part = restored.active_part
assert restored.schema_version == 2
assert [feature.id for feature in restored_part.features] == feature_ids
assert restored_part.rollback_index == 1
assert restored_part.features[3].suppressed
reference = restored_part.features[2].plane_reference
assert reference.feature_id == restored_part.features[1].id
assert reference.role == "END_PLANE"
assert_dimensions((0.080, 0.050, 0.040))
assert ray_hits(0.040, 0.025)

ui = bpy.context.scene.parametric_cad_ui
ui.active_feature_id = restored_part.features[3].id
assert bpy.ops.parametric_cad.roll_forward() == {"FINISHED"}
assert bpy.ops.parametric_cad.toggle_suppression() == {"FINISHED"}
assert not ray_hits(0.040, 0.025)

ui.active_feature_id = restored_part.features[1].id
ui.extrude_distance_mm = 30.0
assert bpy.ops.parametric_cad.apply_extrude() == {"FINISHED"}
assert_dimensions((0.080, 0.050, 0.030))
assert not ray_hits(0.040, 0.025)
print("BLENDER_PARAMETRIC_CAD_M3_VALIDATION_OK")
