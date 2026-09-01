"""Blender 5.1.2 M4 validation: semantic faces, face sketches, and Revolve."""

from __future__ import annotations

import json
import sys
import tempfile
from math import isclose
from pathlib import Path

import bpy

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import blender_parametric_cad
from blender_parametric_cad.blender.adapter import load_document_from_scene, save_document_to_scene
from blender_parametric_cad.blender.operators.selection import _face_reference
from blender_parametric_cad.blender.viewport.provenance import get_face_provenance
from blender_parametric_cad.features.revolve import RevolveFeature
from blender_parametric_cad.sketch.entities import SketchLine
from blender_parametric_cad.sketch.plane import resolve_sketch_plane_from_history


def result_object(part_id: str):
    return next(
        item
        for item in bpy.data.objects
        if item.get("cad_generated") and item.get("cad_part_id") == part_id
    )


def document():
    return load_document_from_scene(scene)


def new_part():
    assert bpy.ops.parametric_cad.new_part() == {"FINISHED"}
    return document().active_part.id


def new_sketch(reference: str = "DATUM|XY"):
    ui.new_sketch_reference = reference
    assert bpy.ops.parametric_cad.new_sketch() == {"FINISHED"}
    return document().active_part.features[-1]


def finish_sketch():
    assert bpy.ops.parametric_cad.finish_sketch() == {"FINISHED"}


def numeric_rectangle(x_mm: float, y_mm: float, width_mm: float, height_mm: float):
    ui.rectangle_x_mm = x_mm
    ui.rectangle_y_mm = y_mm
    ui.rectangle_width_mm = width_mm
    ui.rectangle_height_mm = height_mm
    assert bpy.ops.parametric_cad.numeric_rectangle() == {"FINISHED"}


def extrude(operation="NEW", distance_mm=20.0):
    ui.extrude_operation = operation
    ui.extrude_depth_mode = "BLIND"
    ui.extrude_distance_mm = distance_mm
    assert bpy.ops.parametric_cad.extrude() == {"FINISHED"}
    return document().active_part.features[-1]


def revolve(operation="NEW", axis_type="DATUM_AXIS", axis="Z", line_id="NONE"):
    ui.revolve_operation = operation
    ui.revolve_axis_type = axis_type
    ui.revolve_axis = axis
    if axis_type == "SKETCH_LINE":
        ui.revolve_axis_line_id = line_id
    ui.revolve_angle_deg = 360.0
    assert bpy.ops.parametric_cad.revolve() == {"FINISHED"}
    return document().active_part.features[-1]


def set_face_reference(feature_id: str, role: str, source_entity_id=None):
    data = {
        "reference_type": "FACE",
        "feature_id": feature_id,
        "role": role,
    }
    if source_entity_id is not None:
        data["source_entity_id"] = source_entity_id
    ui.selected_face_reference = json.dumps(data, separators=(",", ":"))


def assert_dimensions(part_id: str, expected, tolerance=1e-5):
    actual = sorted(result_object(part_id).dimensions)
    assert all(isclose(value, target, abs_tol=tolerance) for value, target in zip(actual, sorted(expected))), (
        actual,
        expected,
    )


blender_parametric_cad.register()
scene = bpy.context.scene
ui = scene.parametric_cad_ui

# A/B: provenance maps only temporary current-mesh polygons to semantic roles;
# the document itself stores the stable Extrude UUID and source line UUID.
base_id = new_part()
base_sketch = new_sketch()
numeric_rectangle(-40.0, -25.0, 80.0, 50.0)
finish_sketch()
base_extrude = extrude(distance_mm=20.0)
base_object = result_object(base_id)
provenance = get_face_provenance(base_object)
assert provenance[0].role == "START_FACE"
assert provenance[1].role == "END_FACE"
side_source_id = provenance[2].source_entity_id
assert _face_reference(base_object, 1).role == "END_FACE"
assert _face_reference(base_object, 2).source_entity_id == side_source_id

set_face_reference(base_extrude.id, "END_FACE")
end_sketch = new_sketch()
assert end_sketch.plane_reference.reference_type == "FACE"
assert end_sketch.plane_reference.role == "END_FACE"
assert resolve_sketch_plane_from_history(document().active_part, end_sketch.id).origin == (
    0.0,
    0.0,
    0.020,
)
finish_sketch()

set_face_reference(base_extrude.id, "SIDE_FACE", side_source_id)
side_sketch = new_sketch()
assert side_sketch.plane_reference.role == "SIDE_FACE"
assert side_sketch.plane_reference.source_entity_id == side_source_id
side_plane = resolve_sketch_plane_from_history(document().active_part, side_sketch.id)
assert side_plane.origin == (-0.040, -0.025, 0.0)
finish_sketch()

ui.active_feature_id = base_extrude.id
ui.extrude_operation = "NEW"
ui.extrude_depth_mode = "BLIND"
ui.extrude_distance_mm = 40.0
assert bpy.ops.parametric_cad.apply_extrude() == {"FINISHED"}
assert resolve_sketch_plane_from_history(document().active_part, end_sketch.id).origin == (
    0.0,
    0.0,
    0.040,
)
ui.active_feature_id = base_sketch.id
assert bpy.ops.parametric_cad.edit_sketch() == {"FINISHED"}
numeric_rectangle(-50.0, -30.0, 100.0, 60.0)
finish_sketch()
side_plane = resolve_sketch_plane_from_history(document().active_part, side_sketch.id)
assert side_plane.origin == (-0.050, -0.030, 0.0)

# C: a datum Z axis Revolve creates a valid solid from an XZ profile.
datum_id = new_part()
datum_sketch = new_sketch("DATUM|XZ")
numeric_rectangle(0.0, 0.0, 10.0, 20.0)
finish_sketch()
datum_revolve = revolve()
assert isinstance(datum_revolve, RevolveFeature)
assert datum_revolve.axis_reference.reference_type == "DATUM_AXIS"
assert datum_revolve.status == "OK", datum_revolve.error_message
assert_dimensions(datum_id, (0.020, 0.020, 0.020))

# D: a construction SketchLine is a semantic axis; moving its endpoints changes
# the same Revolve reference on rebuild.
line_id = new_part()
line_sketch = new_sketch("DATUM|XZ")
numeric_rectangle(0.0, 0.0, 10.0, 20.0)
line_document = document()
line_sketch = line_document.active_part.get_feature(line_sketch.id)
axis_line = SketchLine(x1=0.0, y1=0.0, x2=0.0, y2=0.020, construction=True)
line_sketch.entities.append(axis_line)
save_document_to_scene(scene, line_document)
finish_sketch()
line_revolve = revolve(axis_type="SKETCH_LINE", line_id=axis_line.id)
assert line_revolve.status == "OK", line_revolve.error_message
line_document = document()
line_sketch = line_document.active_part.get_feature(line_sketch.id)
axis_line = next(entity for entity in line_sketch.entities if entity.id == axis_line.id)
axis_line.x1 = axis_line.x2 = 0.003
save_document_to_scene(scene, line_document)
ui.active_feature_id = line_revolve.id
ui.revolve_operation = "NEW"
ui.revolve_axis_type = "SKETCH_LINE"
ui.revolve_axis_line_id = axis_line.id
ui.revolve_angle_deg = 360.0
assert bpy.ops.parametric_cad.apply_revolve() == {"FINISHED"}
line_revolve = document().active_part.get_feature(line_revolve.id)
assert line_revolve.status == "OK", line_revolve.error_message
assert line_revolve.axis_reference.entity_id == axis_line.id

# E: Revolve uses the same generic profile tool for Add and Remove.
add_id = new_part()
add_sketch = new_sketch("DATUM|XY")
numeric_rectangle(-40.0, -25.0, 80.0, 50.0)
finish_sketch()
add_base = extrude(distance_mm=20.0)
add_profile = new_sketch("DATUM|XZ")
numeric_rectangle(0.0, 0.0, 45.0, 10.0)
finish_sketch()
add_revolve = revolve(operation="ADD")
assert add_revolve.status == "OK", add_revolve.error_message
assert_dimensions(add_id, (0.090, 0.090, 0.020), tolerance=2e-4)

remove_id = new_part()
remove_sketch = new_sketch("DATUM|XY")
numeric_rectangle(-40.0, -25.0, 80.0, 50.0)
finish_sketch()
remove_base = extrude(distance_mm=20.0)
remove_profile = new_sketch("DATUM|XZ")
numeric_rectangle(0.0, 0.0, 10.0, 20.0)
finish_sketch()
remove_revolve = revolve(operation="REMOVE")
assert remove_revolve.status == "OK", remove_revolve.error_message
assert_dimensions(remove_id, (0.080, 0.050, 0.020))

# Save/reopen preserves semantic references and Revolve parameters.
blend_path = str(Path(tempfile.gettempdir()) / "blender_parametric_cad_m4_validation.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend_path)
bpy.ops.wm.open_mainfile(filepath=blend_path)
scene = bpy.context.scene
ui = scene.parametric_cad_ui
restored = load_document_from_scene(scene)
restored_revolve = restored.get_part(remove_id).get_feature(remove_revolve.id)
assert isinstance(restored_revolve, RevolveFeature)
assert restored_revolve.axis_reference.axis == "Z"
assert restored_revolve.operation == "REMOVE"

print("BLENDER_PARAMETRIC_CAD_M4_VALIDATION_OK")
