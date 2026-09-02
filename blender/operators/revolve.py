"""Revolve feature creation and editing operators."""

from __future__ import annotations

from math import radians

import bpy

from ...core.references import AxisReference
from ...core.part import previous_body_feature
from ...features.revolve import RevolveFeature
from ...sketch.entities import SketchLine
from ...sketch.sketch import SketchFeature
from ..adapter import load_document_from_scene, rebuild_part, save_document_to_scene


def _previous_body_feature(part, before_index: int):
    return previous_body_feature(part, before_index)


def _axis_reference(ui, sketch: SketchFeature) -> AxisReference:
    direction = -1 if ui.revolve_axis_reverse else 1
    if ui.revolve_axis_type == "DATUM_AXIS":
        return AxisReference(
            reference_type="DATUM_AXIS",
            axis=ui.revolve_axis,
            direction=direction,
        )
    return AxisReference(
        reference_type="SKETCH_LINE",
        sketch_id=sketch.id,
        entity_id=ui.revolve_axis_line_id,
        direction=direction,
    )


def _dependencies(part, sketch: SketchFeature, operation: str, axis: AxisReference, before_index=None):
    dependencies = [sketch.id]
    if axis.reference_type == "SKETCH_LINE" and axis.sketch_id not in dependencies:
        dependencies.append(axis.sketch_id)
    if operation != "NEW":
        previous = _previous_body_feature(
            part, len(part.features) if before_index is None else before_index
        )
        if previous is not None and previous.id not in dependencies:
            dependencies.append(previous.id)
    return dependencies


def _validate_operation(part, operation: str, before_index: int | None = None) -> str | None:
    has_body = _previous_body_feature(
        part, len(part.features) if before_index is None else before_index
    ) is not None
    if operation in {"ADD", "REMOVE"} and not has_body:
        return f"Revolve {operation.title()} requires an earlier body feature."
    if operation == "NEW" and has_body:
        return "Revolve New cannot follow an existing body; use Add or Remove."
    return None


def _report_rebuild(operator, result) -> bool:
    if result.success:
        return True
    message = result.errors[0].message if result.errors else "Part rebuild failed"
    operator.report({"ERROR"}, message)
    return False


def _create_revolve(operator, context):
    scene = context.scene
    ui = scene.parametric_cad_ui
    document = load_document_from_scene(scene)
    part = document.active_part
    sketch = part.get_feature(ui.active_feature_id) if part else None
    if not isinstance(sketch, SketchFeature):
        operator.report({"ERROR"}, "Select a Sketch feature")
        return {"CANCELLED"}
    operation_error = _validate_operation(part, ui.revolve_operation)
    if operation_error:
        operator.report({"ERROR"}, operation_error)
        return {"CANCELLED"}
    axis = _axis_reference(ui, sketch)
    if axis.reference_type == "SKETCH_LINE":
        if axis.entity_id in {None, "", "NONE"} or not any(
            isinstance(entity, SketchLine) and entity.id == axis.entity_id
            for entity in sketch.entities
        ):
            operator.report({"ERROR"}, "Select a valid SketchLine axis")
            return {"CANCELLED"}
    revolve = RevolveFeature(
        name=part.next_feature_name("Revolve"),
        sketch_id=sketch.id,
        axis_reference=axis,
        angle=radians(ui.revolve_angle_deg),
        operation=ui.revolve_operation,
        dependencies=_dependencies(part, sketch, ui.revolve_operation, axis),
    )
    part.add_feature(revolve)
    ui.active_feature_id = revolve.id
    ui.active_sketch_id = ""
    ui.mode = "FEATURE_EDIT"
    save_document_to_scene(scene, document)
    _report_rebuild(operator, rebuild_part(scene, part.id))
    return {"FINISHED"}


class PARAMETRIC_CAD_OT_revolve(bpy.types.Operator):
    bl_idname = "parametric_cad.revolve"
    bl_label = "Revolve"
    bl_description = "Revolve the selected closed profile as New, Add, or Remove"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _create_revolve(self, context)


class PARAMETRIC_CAD_OT_apply_revolve(bpy.types.Operator):
    bl_idname = "parametric_cad.apply_revolve"
    bl_label = "Apply Revolve"
    bl_description = "Update Revolve history and regenerate this Part Studio"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        ui = scene.parametric_cad_ui
        document = load_document_from_scene(scene)
        part = document.active_part
        revolve = part.get_feature(ui.active_feature_id) if part else None
        if not isinstance(revolve, RevolveFeature):
            self.report({"ERROR"}, "Select a Revolve feature")
            return {"CANCELLED"}
        sketch = part.get_feature(revolve.sketch_id)
        if not isinstance(sketch, SketchFeature):
            self.report({"ERROR"}, "Revolve source Sketch is unavailable")
            return {"CANCELLED"}
        operation_error = _validate_operation(
            part, ui.revolve_operation, part.get_feature_index(revolve.id)
        )
        if operation_error:
            self.report({"ERROR"}, operation_error)
            return {"CANCELLED"}
        axis = _axis_reference(ui, sketch)
        revolve.axis_reference = axis
        revolve.operation = ui.revolve_operation
        revolve.angle = radians(ui.revolve_angle_deg)
        revolve.dependencies = _dependencies(
            part, sketch, revolve.operation, axis, part.get_feature_index(revolve.id)
        )
        save_document_to_scene(scene, document)
        _report_rebuild(self, rebuild_part(scene, part.id))
        return {"FINISHED"}


CLASSES = (PARAMETRIC_CAD_OT_revolve, PARAMETRIC_CAD_OT_apply_revolve)
