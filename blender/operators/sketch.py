"""Sketch feature lifecycle operators."""

from __future__ import annotations

import json
from math import pi

import bpy

from ...core.serialization import feature_from_dict, feature_to_dict
from ...core.references import TopoReference
from ...sketch.numeric import (
    arc_parameters,
    circle_parameters,
    rectangle_parameters,
    set_arc,
    set_circle,
    set_rectangle,
)
from ...sketch.plane import (
    PlaneResolutionError,
    ResolvedPlane,
    resolve_sketch_plane_from_history,
)
from ...sketch.sketch import SketchFeature
from ..adapter import load_document_from_scene, rebuild_part, save_document_to_scene
from ..viewport.projection import screen_to_sketch
from ..viewport.sketch_overlay import clear_face_selection, clear_preview, tag_redraw


def _orient_to_plane(context, plane: ResolvedPlane) -> None:
    if context.area and context.area.type == "VIEW_3D":
        normal = tuple(round(value) for value in plane.normal)
        view_type = {
            (0, 0, 1): "TOP",
            (0, 0, -1): "BOTTOM",
            (0, -1, 0): "FRONT",
            (0, 1, 0): "BACK",
            (1, 0, 0): "RIGHT",
            (-1, 0, 0): "LEFT",
        }.get(normal, "TOP")
        window_region = next(
            (region for region in context.area.regions if region.type == "WINDOW"), None
        )
        if window_region is None:
            return
        try:
            with context.temp_override(area=context.area, region=window_region):
                bpy.ops.view3d.view_axis(type=view_type, align_active=False)
            context.space_data.region_3d.view_perspective = "ORTHO"
        except RuntimeError:
            pass


def _begin_edit(context, part, sketch: SketchFeature, is_new: bool) -> None:
    plane = resolve_sketch_plane_from_history(part, sketch.id)
    sketch.apply_resolved_plane(plane)
    ui = context.scene.parametric_cad_ui
    ui.mode = "SKETCH_EDIT"
    ui.active_feature_id = sketch.id
    ui.active_sketch_id = sketch.id
    ui.active_sketch_entity_id = ""
    ui.sketch_session_new = is_new
    ui.sketch_session_backup = "" if is_new else json.dumps(feature_to_dict(sketch))
    clear_preview()
    _orient_to_plane(context, plane)
    if context.area and context.area.type == "VIEW_3D":
        window_region = next(
            (region for region in context.area.regions if region.type == "WINDOW"), None
        )
        if window_region is not None:
            with context.temp_override(region=window_region):
                bpy.ops.parametric_cad.track_sketch_cursor(
                    "INVOKE_DEFAULT", sketch_id=sketch.id
                )
    tag_redraw()


class PARAMETRIC_CAD_OT_track_sketch_cursor(bpy.types.Operator):
    bl_idname = "parametric_cad.track_sketch_cursor"
    bl_label = "Track Sketch Coordinates"
    bl_options = {"INTERNAL"}

    sketch_id: bpy.props.StringProperty()

    def invoke(self, context, _event):
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        ui = context.scene.parametric_cad_ui
        if ui.mode != "SKETCH_EDIT" or ui.active_sketch_id != self.sketch_id:
            return {"FINISHED"}
        if event.type == "MOUSEMOVE":
            document = load_document_from_scene(context.scene)
            part = document.active_part
            sketch = part.get_feature(self.sketch_id) if part else None
            if isinstance(sketch, SketchFeature):
                try:
                    sketch.apply_resolved_plane(
                        resolve_sketch_plane_from_history(part, sketch.id)
                    )
                    point = screen_to_sketch(context, event, sketch)
                except PlaneResolutionError:
                    point = None
                if point is not None:
                    ui.mouse_x_mm = point[0] * 1000.0
                    ui.mouse_y_mm = point[1] * 1000.0
        return {"PASS_THROUGH"}


class PARAMETRIC_CAD_OT_new_sketch(bpy.types.Operator):
    bl_idname = "parametric_cad.new_sketch"
    bl_label = "New Sketch"
    bl_description = "Create a sketch on the selected datum plane or face"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        document = load_document_from_scene(context.scene)
        part = document.active_part
        if part is None:
            self.report({"ERROR"}, "Create a Part first")
            return {"CANCELLED"}
        ui = context.scene.parametric_cad_ui
        if ui.selected_face_reference:
            try:
                face = TopoReference.from_dict(json.loads(ui.selected_face_reference))
                sketch = SketchFeature.on_face(part.next_feature_name("Sketch"), face)
            except (TypeError, ValueError, KeyError) as exc:
                self.report({"ERROR"}, f"Invalid selected face: {exc}")
                return {"CANCELLED"}
        else:
            reference = ui.new_sketch_reference
            tokens = reference.split("|")
            if tokens[0] == "FEATURE" and len(tokens) == 3:
                sketch = SketchFeature.on_feature_plane(
                    part.next_feature_name("Sketch"), tokens[1], tokens[2]
                )
            else:
                plane_type = tokens[1] if len(tokens) == 2 else "XY"
                sketch = SketchFeature.on_plane(
                    part.next_feature_name("Sketch"), plane_type
                )
        part.add_feature(sketch)
        try:
            _begin_edit(context, part, sketch, True)
        except PlaneResolutionError as exc:
            part.remove_feature(sketch.id)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        ui.selected_face_reference = ""
        clear_face_selection()
        save_document_to_scene(context.scene, document)
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_edit_sketch(bpy.types.Operator):
    bl_idname = "parametric_cad.edit_sketch"
    bl_label = "Edit Sketch"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        document = load_document_from_scene(context.scene)
        part = document.active_part
        feature_id = context.scene.parametric_cad_ui.active_feature_id
        sketch = part.get_feature(feature_id) if part else None
        if not isinstance(sketch, SketchFeature):
            self.report({"ERROR"}, "Select a Sketch feature")
            return {"CANCELLED"}
        try:
            _begin_edit(context, part, sketch, False)
        except PlaneResolutionError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_finish_sketch(bpy.types.Operator):
    bl_idname = "parametric_cad.finish_sketch"
    bl_label = "Finish Sketch"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ui = context.scene.parametric_cad_ui
        document = load_document_from_scene(context.scene)
        save_document_to_scene(context.scene, document)
        ui.mode = "FEATURE_EDIT"
        ui.active_sketch_entity_id = ""
        ui.sketch_session_new = False
        ui.sketch_session_backup = ""
        clear_preview()
        part = document.active_part
        if part:
            result = rebuild_part(context.scene, part.id)
            if not result.success and result.errors:
                self.report({"WARNING"}, result.errors[0].message)
        tag_redraw()
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_cancel_sketch(bpy.types.Operator):
    bl_idname = "parametric_cad.cancel_sketch"
    bl_label = "Cancel"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ui = context.scene.parametric_cad_ui
        document = load_document_from_scene(context.scene)
        part = document.active_part
        if part is not None:
            index = part.get_feature_index(ui.active_sketch_id)
            if ui.sketch_session_new:
                part.remove_feature(ui.active_sketch_id)
                ui.active_feature_id = ""
            elif index is not None and ui.sketch_session_backup:
                part.features[index] = feature_from_dict(json.loads(ui.sketch_session_backup))
            save_document_to_scene(context.scene, document)
        ui.mode = "IDLE"
        ui.active_sketch_id = ""
        ui.active_sketch_entity_id = ""
        ui.sketch_session_new = False
        ui.sketch_session_backup = ""
        clear_preview()
        tag_redraw()
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_clear_sketch(bpy.types.Operator):
    bl_idname = "parametric_cad.clear_sketch"
    bl_label = "Delete All Geometry"
    bl_description = "Remove every entity from the active sketch"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ui = context.scene.parametric_cad_ui
        document = load_document_from_scene(context.scene)
        part = document.active_part
        sketch = part.get_feature(ui.active_sketch_id) if part else None
        if not isinstance(sketch, SketchFeature):
            return {"CANCELLED"}
        sketch.entities.clear()
        sketch.deleted_regions.clear()
        ui.active_sketch_entity_id = ""
        save_document_to_scene(context.scene, document)
        tag_redraw()
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_numeric_rectangle(bpy.types.Operator):
    bl_idname = "parametric_cad.numeric_rectangle"
    bl_label = "Update Rectangle"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ui = context.scene.parametric_cad_ui
        document = load_document_from_scene(context.scene)
        part = document.active_part
        sketch = part.get_feature(ui.active_sketch_id) if part else None
        if not isinstance(sketch, SketchFeature):
            return {"CANCELLED"}
        try:
            set_rectangle(
                sketch,
                ui.rectangle_x_mm / 1000.0,
                ui.rectangle_y_mm / 1000.0,
                ui.rectangle_width_mm / 1000.0,
                ui.rectangle_height_mm / 1000.0,
                ui.active_sketch_entity_id or None,
            )
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        save_document_to_scene(context.scene, document)
        tag_redraw()
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_numeric_circle(bpy.types.Operator):
    bl_idname = "parametric_cad.numeric_circle"
    bl_label = "Update Circle"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ui = context.scene.parametric_cad_ui
        document = load_document_from_scene(context.scene)
        part = document.active_part
        sketch = part.get_feature(ui.active_sketch_id) if part else None
        if not isinstance(sketch, SketchFeature):
            return {"CANCELLED"}
        try:
            set_circle(
                sketch,
                ui.circle_x_mm / 1000.0,
                ui.circle_y_mm / 1000.0,
                ui.circle_diameter_mm / 1000.0,
                ui.active_sketch_entity_id or None,
            )
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        save_document_to_scene(context.scene, document)
        tag_redraw()
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_numeric_arc(bpy.types.Operator):
    bl_idname = "parametric_cad.numeric_arc"
    bl_label = "Update Arc"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ui = context.scene.parametric_cad_ui
        document = load_document_from_scene(context.scene)
        part = document.active_part
        sketch = part.get_feature(ui.active_sketch_id) if part else None
        if not isinstance(sketch, SketchFeature):
            return {"CANCELLED"}
        if arc_parameters(sketch, ui.active_sketch_entity_id or None) is None:
            self.report({"ERROR"}, "Select an existing Arc to edit its dimensions.")
            return {"CANCELLED"}
        try:
            set_arc(
                sketch,
                ui.arc_x_mm / 1000.0,
                ui.arc_y_mm / 1000.0,
                ui.arc_radius_mm / 1000.0,
                ui.arc_start_deg * pi / 180.0,
                ui.arc_end_deg * pi / 180.0,
                ui.active_sketch_entity_id or None,
            )
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        save_document_to_scene(context.scene, document)
        tag_redraw()
        return {"FINISHED"}


CLASSES = (
    PARAMETRIC_CAD_OT_track_sketch_cursor,
    PARAMETRIC_CAD_OT_new_sketch,
    PARAMETRIC_CAD_OT_edit_sketch,
    PARAMETRIC_CAD_OT_finish_sketch,
    PARAMETRIC_CAD_OT_cancel_sketch,
    PARAMETRIC_CAD_OT_clear_sketch,
    PARAMETRIC_CAD_OT_numeric_rectangle,
    PARAMETRIC_CAD_OT_numeric_circle,
    PARAMETRIC_CAD_OT_numeric_arc,
)
