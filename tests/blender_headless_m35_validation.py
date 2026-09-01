"""Blender 5.1.2 M3.5 validation: Part Studios and Feature management."""

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
from blender_parametric_cad.sketch.entities import SketchCircle, SketchLine


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


def create_body(width: float, height: float, depth_mm: float):
    bpy.ops.parametric_cad.new_part()
    ui = bpy.context.scene.parametric_cad_ui
    ui.new_sketch_reference = "DATUM|XY"
    assert bpy.ops.parametric_cad.new_sketch() == {"FINISHED"}
    document = load_document_from_scene(bpy.context.scene)
    part = document.active_part
    sketch = part.features[0]
    sketch.entities = [
        SketchLine(x1=0.0, y1=0.0, x2=width, y2=0.0),
        SketchLine(x1=width, y1=0.0, x2=width, y2=height),
        SketchLine(x1=width, y1=height, x2=0.0, y2=height),
        SketchLine(x1=0.0, y1=height, x2=0.0, y2=0.0),
    ]
    save_document_to_scene(bpy.context.scene, document)
    assert bpy.ops.parametric_cad.finish_sketch() == {"FINISHED"}
    ui.extrude_distance_mm = depth_mm
    assert bpy.ops.parametric_cad.extrude() == {"FINISHED"}
    document = load_document_from_scene(bpy.context.scene)
    part = document.active_part
    return part.id, part.features[0].id, part.features[1].id


def activate(part_id: str) -> None:
    ui = bpy.context.scene.parametric_cad_ui
    ui.active_part_id = part_id
    document = load_document_from_scene(bpy.context.scene)
    assert document.active_part_id == part_id
    assert ui.active_feature_id == ""


blender_parametric_cad.register()
scene = bpy.context.scene
ui = scene.parametric_cad_ui

# Independent Part Studios may use duplicate Feature names.
first_id, first_sketch_id, first_extrude_id = create_body(0.080, 0.050, 40.0)
second_id, second_sketch_id, second_extrude_id = create_body(0.030, 0.030, 15.0)
document = load_document_from_scene(scene)
assert [part.name for part in document.parts] == ["Part Studio 1", "Part Studio 2"]
assert document.parts[0].features[0].name == document.parts[1].features[0].name
assert document.parts[0].features[0].id != document.parts[1].features[0].id
assert_dimensions(first_id, (0.080, 0.050, 0.040))
assert_dimensions(second_id, (0.030, 0.030, 0.015))

# Switch back to an older Part Studio and edit only its extrusion.
activate(first_id)
ui.active_feature_id = first_extrude_id
ui.extrude_distance_mm = 30.0
assert bpy.ops.parametric_cad.apply_extrude() == {"FINISHED"}
assert_dimensions(first_id, (0.080, 0.050, 0.030))
assert_dimensions(second_id, (0.030, 0.030, 0.015))

# Rename by UUID; the downstream extrusion continues to resolve the same sketch.
assert bpy.ops.parametric_cad.rename_feature(
    "EXEC_DEFAULT", feature_id=first_sketch_id, name="Base Sketch"
) == {"FINISHED"}
document = load_document_from_scene(scene)
first = document.get_part(first_id)
assert first.get_feature(first_sketch_id).name == "Base Sketch"
assert first.get_feature(first_extrude_id).sketch_id == first_sketch_id

# Build an END_PLANE sketch and Through All remove in Part Studio 1.
ui.active_feature_id = first_extrude_id
ui.new_sketch_reference = f"FEATURE|{first_extrude_id}|END_PLANE"
assert bpy.ops.parametric_cad.new_sketch() == {"FINISHED"}
document = load_document_from_scene(scene)
first = document.get_part(first_id)
hole_sketch = first.features[2]
hole_sketch.entities = [SketchCircle(cx=0.040, cy=0.025, radius=0.005)]
save_document_to_scene(scene, document)
assert bpy.ops.parametric_cad.finish_sketch() == {"FINISHED"}
assert bpy.ops.parametric_cad.cut() == {"FINISHED"}
document = load_document_from_scene(scene)
first = document.get_part(first_id)
hole_id, cut_id = first.features[2].id, first.features[3].id

# Leaf delete restores the uncut solid and leaves the sketch.
assert bpy.ops.parametric_cad.delete_feature(
    "EXEC_DEFAULT", feature_id=cut_id
) == {"FINISHED"}
first = load_document_from_scene(scene).get_part(first_id)
assert [feature.id for feature in first.features] == [
    first_sketch_id,
    first_extrude_id,
    hole_id,
]
assert_dimensions(first_id, (0.080, 0.050, 0.030))

# Recreate the remove, then cascade-delete its source sketch.
ui.active_feature_id = hole_id
assert bpy.ops.parametric_cad.cut() == {"FINISHED"}
document = load_document_from_scene(scene)
first = document.get_part(first_id)
recreated_cut_id = first.features[3].id
first.rollback_index = 3
first.features[3].suppressed = True
save_document_to_scene(scene, document)
assert bpy.ops.parametric_cad.delete_feature(
    "EXEC_DEFAULT", feature_id=hole_id
) == {"FINISHED"}
first = load_document_from_scene(scene).get_part(first_id)
assert [feature.id for feature in first.features] == [first_sketch_id, first_extrude_id]
assert first.get_feature(recreated_cut_id) is None
assert first.rollback_index is None
assert_dimensions(second_id, (0.030, 0.030, 0.015))

# The second Part Studio remains independently editable.
activate(second_id)
ui.active_feature_id = second_extrude_id
ui.extrude_distance_mm = 12.0
assert bpy.ops.parametric_cad.apply_extrude() == {"FINISHED"}
assert_dimensions(second_id, (0.030, 0.030, 0.012))
assert_dimensions(first_id, (0.080, 0.050, 0.030))

# Part Studio rename is cosmetic, and active deletion removes only its result object.
activate(first_id)
assert bpy.ops.parametric_cad.rename_part(
    "EXEC_DEFAULT", name="Bracket"
) == {"FINISHED"}
assert load_document_from_scene(scene).get_part(first_id).name == "Bracket"
third_id, _third_sketch_id, _third_extrude_id = create_body(0.020, 0.010, 5.0)
assert len([item for item in bpy.data.objects if item.get("cad_generated")]) == 3
assert bpy.ops.parametric_cad.delete_part(
    "EXEC_DEFAULT", part_id=third_id
) == {"FINISHED"}
document = load_document_from_scene(scene)
assert document.active_part_id == second_id
assert document.get_part(third_id) is None
assert not [item for item in bpy.data.objects if item.get("cad_part_id") == third_id]

# Save/reopen preserves both Part Studios and the active selection.
blend_path = str(Path(tempfile.gettempdir()) / "blender_parametric_cad_m35_validation.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend_path)
bpy.ops.wm.open_mainfile(filepath=blend_path)
scene = bpy.context.scene
ui = scene.parametric_cad_ui
restored = load_document_from_scene(scene)
assert len(restored.parts) == 2
assert restored.active_part_id == second_id
assert restored.get_part(first_id).name == "Bracket"
assert restored.get_part(first_id).get_feature(first_sketch_id).name == "Base Sketch"
assert_dimensions(first_id, (0.080, 0.050, 0.030))
assert_dimensions(second_id, (0.030, 0.030, 0.012))

# Both restored Part Studios can still be selected and edited.
activate(first_id)
ui.active_feature_id = first_extrude_id
ui.extrude_distance_mm = 25.0
assert bpy.ops.parametric_cad.apply_extrude() == {"FINISHED"}
activate(second_id)
ui.active_feature_id = second_extrude_id
ui.extrude_distance_mm = 10.0
assert bpy.ops.parametric_cad.apply_extrude() == {"FINISHED"}
assert_dimensions(first_id, (0.080, 0.050, 0.025))
assert_dimensions(second_id, (0.030, 0.030, 0.010))
assert len([item for item in bpy.data.objects if item.get("cad_generated")]) == 2

print("BLENDER_PARAMETRIC_CAD_M35_VALIDATION_OK")
