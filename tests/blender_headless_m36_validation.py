"""Blender 5.1.2 M3.6 validation: sketch usability and unified Extrude."""

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
    save_document_to_scene,
)
from blender_parametric_cad.blender.viewport.sketch_overlay import _entity_segments
from blender_parametric_cad.sketch.entities import SketchLine
from blender_parametric_cad.sketch.plane import resolve_sketch_plane_from_history


def result_object(part_id: str):
    return next(
        item
        for item in bpy.data.objects
        if item.get("cad_generated") and item.get("cad_part_id") == part_id
    )


def assert_dimensions(part_id: str, expected) -> None:
    actual = sorted(result_object(part_id).dimensions)
    assert all(
        abs(value - target) < 1e-6
        for value, target in zip(actual, sorted(expected))
    ), (actual, expected)


def ray(part_id: str, x: float, y: float):
    return result_object(part_id).ray_cast(
        (x, y, 0.1), (0.0, 0.0, -1.0), distance=0.2
    )


def activate(part_id: str) -> None:
    scene.parametric_cad_ui.active_part_id = part_id
    assert load_document_from_scene(scene).active_part_id == part_id


def new_sketch(reference: str = "DATUM|XY"):
    ui.new_sketch_reference = reference
    assert bpy.ops.parametric_cad.new_sketch() == {"FINISHED"}
    document = load_document_from_scene(scene)
    return document.active_part.features[-1]


def numeric_rectangle(x_mm: float, y_mm: float, width_mm: float, height_mm: float):
    ui.rectangle_x_mm = x_mm
    ui.rectangle_y_mm = y_mm
    ui.rectangle_width_mm = width_mm
    ui.rectangle_height_mm = height_mm
    assert bpy.ops.parametric_cad.numeric_rectangle() == {"FINISHED"}


def numeric_circle(x_mm: float, y_mm: float, diameter_mm: float):
    ui.circle_x_mm = x_mm
    ui.circle_y_mm = y_mm
    ui.circle_diameter_mm = diameter_mm
    assert bpy.ops.parametric_cad.numeric_circle() == {"FINISHED"}


def unified_extrude(operation: str, depth: str, distance_mm: float = 20.0):
    ui.extrude_operation = operation
    ui.extrude_depth_mode = depth
    ui.extrude_distance_mm = distance_mm
    assert bpy.ops.parametric_cad.extrude() == {"FINISHED"}
    return load_document_from_scene(scene).active_part.features[-1]


def create_base(width_mm=80.0, height_mm=50.0, depth_mm=20.0):
    assert bpy.ops.parametric_cad.new_part() == {"FINISHED"}
    sketch = new_sketch()
    numeric_rectangle(-width_mm / 2.0, -height_mm / 2.0, width_mm, height_mm)
    assert bpy.ops.parametric_cad.finish_sketch() == {"FINISHED"}
    extrusion = unified_extrude("NEW", "BLIND", depth_mm)
    document = load_document_from_scene(scene)
    return document.active_part.id, sketch.id, extrusion.id


blender_parametric_cad.register()
scene = bpy.context.scene
ui = scene.parametric_cad_ui

# Mandatory rectangular Through-All Remove using the unified Extrude command.
main_id, base_sketch_id, base_extrude_id = create_base()
slot_sketch = new_sketch(f"FEATURE|{base_extrude_id}|END_PLANE")
numeric_rectangle(-10.0, -5.0, 20.0, 10.0)
slot_entity_ids = [entity.id for entity in load_document_from_scene(scene).active_part.features[-1].entities]
assert bpy.ops.parametric_cad.finish_sketch() == {"FINISHED"}
remove = unified_extrude("REMOVE", "THROUGH_ALL")
assert_dimensions(main_id, (0.080, 0.050, 0.020))
assert not ray(main_id, 0.0, 0.0)[0]
assert ray(main_id, 0.020, 0.015)[0]

# Reference overlay geometry is resolved from semantic history, not stored world space.
document = load_document_from_scene(scene)
part = document.active_part
slot = part.get_feature(slot_sketch.id)
plane = resolve_sketch_plane_from_history(part, slot.id)
slot.apply_resolved_plane(plane)
assert all(abs(point[2] - 0.020) < 1e-9 for point in _entity_segments(slot))
ui.show_sketches = True
ui.active_feature_id = slot.id
ui.mode = "FEATURE_EDIT"

# Base distance rebuild moves the reference overlay and keeps the Remove valid.
ui.active_feature_id = base_extrude_id
ui.extrude_operation = "NEW"
ui.extrude_depth_mode = "BLIND"
ui.extrude_distance_mm = 40.0
assert bpy.ops.parametric_cad.apply_extrude() == {"FINISHED"}
part = load_document_from_scene(scene).active_part
slot = part.get_feature(slot_sketch.id)
plane = resolve_sketch_plane_from_history(part, slot.id)
slot.apply_resolved_plane(plane)
assert all(abs(point[2] - 0.040) < 1e-9 for point in _entity_segments(slot))
assert_dimensions(main_id, (0.080, 0.050, 0.040))
assert not ray(main_id, 0.0, 0.0)[0]

# Numeric Rectangle editing preserves its four entity UUIDs and rebuilds downstream.
ui.active_feature_id = slot_sketch.id
assert bpy.ops.parametric_cad.edit_sketch() == {"FINISHED"}
numeric_rectangle(-12.5, -6.0, 25.0, 12.0)
part = load_document_from_scene(scene).active_part
assert [entity.id for entity in part.get_feature(slot_sketch.id).entities] == slot_entity_ids
assert bpy.ops.parametric_cad.finish_sketch() == {"FINISHED"}
assert not ray(main_id, 0.011, 0.0)[0]

# Outer Rectangle editing updates the final solid parametrically.
ui.active_feature_id = base_sketch_id
assert bpy.ops.parametric_cad.edit_sketch() == {"FINISHED"}
numeric_rectangle(-50.0, -30.0, 100.0, 60.0)
assert bpy.ops.parametric_cad.finish_sketch() == {"FINISHED"}
assert_dimensions(main_id, (0.100, 0.060, 0.040))

# Circle Remove Through All and UUID-preserving Ø10 -> Ø15 numeric edit.
circle_id, _circle_base_sketch, circle_base_extrude = create_base()
circle_sketch = new_sketch(f"FEATURE|{circle_base_extrude}|END_PLANE")
numeric_circle(0.0, 0.0, 10.0)
circle_entity_id = load_document_from_scene(scene).active_part.features[-1].entities[0].id
assert bpy.ops.parametric_cad.finish_sketch() == {"FINISHED"}
unified_extrude("REMOVE", "THROUGH_ALL")
assert not ray(circle_id, 0.004, 0.0)[0]
ui.active_feature_id = circle_sketch.id
assert bpy.ops.parametric_cad.edit_sketch() == {"FINISHED"}
numeric_circle(0.0, 0.0, 15.0)
assert load_document_from_scene(scene).active_part.get_feature(circle_sketch.id).entities[0].id == circle_entity_id
assert bpy.ops.parametric_cad.finish_sketch() == {"FINISHED"}
assert not ray(circle_id, 0.006, 0.0)[0]
assert ray(circle_id, 0.009, 0.0)[0]

# Triangle Remove Through All.
triangle_id, _triangle_base_sketch, triangle_base_extrude = create_base()
triangle = new_sketch(f"FEATURE|{triangle_base_extrude}|END_PLANE")
document = load_document_from_scene(scene)
stored_triangle = document.active_part.get_feature(triangle.id)
stored_triangle.entities = [
    SketchLine(x1=-0.010, y1=-0.005, x2=0.010, y2=-0.005),
    SketchLine(x1=0.010, y1=-0.005, x2=0.0, y2=0.010),
    SketchLine(x1=0.0, y1=0.010, x2=-0.010, y2=-0.005),
]
save_document_to_scene(scene, document)
assert bpy.ops.parametric_cad.finish_sketch() == {"FINISHED"}
unified_extrude("REMOVE", "THROUGH_ALL")
assert not ray(triangle_id, 0.0, 0.0)[0]
assert ray(triangle_id, 0.020, 0.015)[0]

# Rectangle Remove Blind 5 mm creates a pocket from the END_PLANE inward.
blind_id, _blind_base_sketch, blind_base_extrude = create_base()
blind_sketch = new_sketch(f"FEATURE|{blind_base_extrude}|END_PLANE")
numeric_rectangle(-10.0, -5.0, 20.0, 10.0)
assert bpy.ops.parametric_cad.finish_sketch() == {"FINISHED"}
unified_extrude("REMOVE", "BLIND", 5.0)
center_hit = ray(blind_id, 0.0, 0.0)
outside_hit = ray(blind_id, 0.020, 0.015)
assert center_hit[0] and abs(center_hit[1].z - 0.015) < 1e-5, center_hit
assert outside_hit[0] and abs(outside_hit[1].z - 0.020) < 1e-5, outside_hit

# Rectangle Add 10 mm creates one unioned body with a raised boss.
add_id, _add_base_sketch, add_base_extrude = create_base()
add_sketch = new_sketch(f"FEATURE|{add_base_extrude}|END_PLANE")
numeric_rectangle(-10.0, -5.0, 20.0, 10.0)
assert bpy.ops.parametric_cad.finish_sketch() == {"FINISHED"}
unified_extrude("ADD", "BLIND", 10.0)
assert_dimensions(add_id, (0.080, 0.050, 0.030))

# Repeated deletes work in one session after rename/suppress/rollback/switch/reload.
delete_id, delete_sketch_1, delete_extrude_1 = create_base(30.0, 30.0, 10.0)
delete_sketch_2_feature = new_sketch(f"FEATURE|{delete_extrude_1}|END_PLANE")
numeric_rectangle(-5.0, -5.0, 10.0, 10.0)
assert bpy.ops.parametric_cad.finish_sketch() == {"FINISHED"}
delete_extrude_2_feature = unified_extrude("REMOVE", "THROUGH_ALL")
document = load_document_from_scene(scene)
delete_part = document.get_part(delete_id)
delete_part.get_feature(delete_sketch_2_feature.id).name = "Second Sketch"
delete_part.get_feature(delete_extrude_2_feature.id).suppressed = True
delete_part.rollback_index = 3
save_document_to_scene(scene, document)
activate(main_id)
activate(delete_id)

blend_path = str(Path(tempfile.gettempdir()) / "blender_parametric_cad_m36_validation.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend_path)
bpy.ops.wm.open_mainfile(filepath=blend_path)
scene = bpy.context.scene
ui = scene.parametric_cad_ui
activate(delete_id)
delete_order = [
    delete_extrude_2_feature.id,
    delete_sketch_2_feature.id,
    delete_extrude_1,
    delete_sketch_1,
]
for expected_count, feature_id in zip((3, 2, 1, 0), delete_order):
    ui.active_feature_id = feature_id
    assert bpy.ops.parametric_cad.delete_feature(
        "EXEC_DEFAULT", feature_id=feature_id
    ) == {"FINISHED"}
    part = load_document_from_scene(scene).get_part(delete_id)
    assert len(part.features) == expected_count
    assert part.rollback_index is None
assert ui.active_feature_id == ""
assert not [item for item in bpy.data.objects if item.get("cad_part_id") == delete_id]

# All other Part Studios and generated bodies survive save/reopen and repeated deletion.
restored = load_document_from_scene(scene)
for part_id in (main_id, circle_id, triangle_id, blind_id, add_id):
    assert restored.get_part(part_id) is not None
    assert result_object(part_id) is not None
assert len([item for item in bpy.data.objects if item.get("cad_generated")]) == 5

print("BLENDER_PARAMETRIC_CAD_M36_VALIDATION_OK")
