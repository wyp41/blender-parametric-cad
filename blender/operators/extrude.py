"""Create and edit unified NEW, ADD, and REMOVE extrusion features."""

from __future__ import annotations

import bpy

from ...features.extrude import ExtrudeFeature
from ...core.part import previous_body_feature
from ...sketch.profile import ProfileDetector
from ...sketch.sketch import SketchFeature
from ..adapter import load_document_from_scene, rebuild_part, save_document_to_scene


def _report_rebuild(operator, result) -> bool:
    if result.success:
        return True
    message = result.errors[0].message if result.errors else "Part rebuild failed"
    operator.report({"ERROR"}, message)
    return False


def _previous_body_feature(part, before_index: int):
    return previous_body_feature(part, before_index)


def _feature_dependencies(
    part, sketch: SketchFeature, operation: str, before_index: int | None = None
) -> list[str]:
    dependencies = [sketch.id]
    if operation != "NEW":
        previous = _previous_body_feature(
            part, len(part.features) if before_index is None else before_index
        )
        if previous is not None:
            dependencies.append(previous.id)
    return dependencies


def _direction(sketch: SketchFeature, operation: str, depth_mode: str) -> int:
    if (
        operation == "REMOVE"
        and depth_mode == "BLIND"
        and sketch.plane_reference.reference_type == "FEATURE_PLANE"
    ):
        return -1
    return 1


def _create_extrude(operator, context, operation: str, depth_mode: str, legacy=False):
    scene = context.scene
    ui = scene.parametric_cad_ui
    document = load_document_from_scene(scene)
    part = document.active_part
    sketch = part.get_feature(ui.active_feature_id) if part else None
    if not isinstance(sketch, SketchFeature):
        operator.report({"ERROR"}, "Select a Sketch feature")
        return {"CANCELLED"}
    detected = ProfileDetector().detect(sketch)
    if not detected.success:
        operator.report({"ERROR"}, f"Cannot extrude {sketch.name}: {detected.message}")
        return {"CANCELLED"}

    extrude = ExtrudeFeature(
        name=part.next_feature_name("Cut" if legacy else "Extrude"),
        sketch_id=sketch.id,
        distance=ui.extrude_distance_mm / 1000.0,
        direction=_direction(sketch, operation, depth_mode),
        operation=operation,
        depth_mode=depth_mode,
        dependencies=_feature_dependencies(part, sketch, operation),
    )
    part.add_feature(extrude)
    ui.active_feature_id = extrude.id
    ui.feature_name = extrude.name
    ui.feature_create_kind = ""
    ui.active_sketch_id = ""
    ui.mode = "FEATURE_EDIT"
    save_document_to_scene(scene, document)
    _report_rebuild(operator, rebuild_part(scene, part.id))
    return {"FINISHED"}


class PARAMETRIC_CAD_OT_extrude(bpy.types.Operator):
    bl_idname = "parametric_cad.extrude"
    bl_label = "Extrude"
    bl_description = "Extrude the selected closed profile as New, Add, or Remove"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ui = context.scene.parametric_cad_ui
        return _create_extrude(
            self, context, ui.extrude_operation, ui.extrude_depth_mode
        )


class PARAMETRIC_CAD_OT_apply_extrude(bpy.types.Operator):
    bl_idname = "parametric_cad.apply_extrude"
    bl_label = "Apply & Rebuild"
    bl_description = "Update extrusion history and regenerate this Part Studio"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        ui = scene.parametric_cad_ui
        document = load_document_from_scene(scene)
        part = document.active_part
        extrude = part.get_feature(ui.active_feature_id) if part else None
        if not isinstance(extrude, ExtrudeFeature):
            self.report({"ERROR"}, "Select an Extrude feature")
            return {"CANCELLED"}
        sketch = part.get_feature(extrude.sketch_id)
        if not isinstance(sketch, SketchFeature):
            self.report({"ERROR"}, "Extrude source Sketch is unavailable")
            return {"CANCELLED"}
        operation = ui.extrude_operation
        extrude.distance = ui.extrude_distance_mm / 1000.0
        extrude.operation = operation
        extrude.depth_mode = ui.extrude_depth_mode
        extrude.direction = _direction(sketch, operation, extrude.depth_mode)
        extrude.dependencies = _feature_dependencies(
            part, sketch, operation, part.get_feature_index(extrude.id)
        )
        save_document_to_scene(scene, document)
        _report_rebuild(self, rebuild_part(scene, part.id))
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_cut(bpy.types.Operator):
    """Compatibility entry point for M3 files/tests; the main UI uses Extrude."""

    bl_idname = "parametric_cad.cut"
    bl_label = "Remove Through All"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _create_extrude(self, context, "REMOVE", "THROUGH_ALL", legacy=True)


CLASSES = (
    PARAMETRIC_CAD_OT_extrude,
    PARAMETRIC_CAD_OT_apply_extrude,
    PARAMETRIC_CAD_OT_cut,
)
