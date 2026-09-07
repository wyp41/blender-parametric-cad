"""Safe entry points from disposable result meshes back into CAD history."""

from __future__ import annotations

import bpy

from ...features.extrude import ExtrudeFeature
from ...features.revolve import RevolveFeature
from ...core.part import BODY_FEATURE_TYPES, previous_body_feature
from ...sketch.sketch import SketchFeature
from ..adapter import (
    CadDocumentError,
    load_document_from_scene,
    sync_active_part_from_object,
    validate_cad_document,
)
from ..viewport.sketch_overlay import tag_redraw


class PARAMETRIC_CAD_OT_edit_cad_history(bpy.types.Operator):
    bl_idname = "parametric_cad.edit_cad_history"
    bl_label = "Edit CAD History"
    bl_description = "Open the source Sketch or Feature instead of editing a generated mesh"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = getattr(getattr(context, "view_layer", None), "objects", None)
        active = getattr(obj, "active", None)
        return active is not None and bool(active.get("cad_generated"))

    def execute(self, context):
        scene = context.scene
        obj = getattr(context.view_layer.objects, "active", None)
        if obj is None or not obj.get("cad_generated"):
            self.report({"ERROR"}, "Select a generated CAD result mesh first.")
            return {"CANCELLED"}
        if getattr(obj, "mode", "OBJECT") == "EDIT":
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except RuntimeError:
                self.report({"ERROR"}, "Leave generated mesh Edit Mode before opening CAD history.")
                return {"CANCELLED"}
        try:
            part_id = sync_active_part_from_object(scene, obj)
            document = load_document_from_scene(scene)
        except CadDocumentError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        part = document.get_part(part_id) if part_id else document.active_part
        if part is None:
            self.report({"ERROR"}, "The generated mesh has no valid Part Studio.")
            return {"CANCELLED"}

        feature_id = obj.get("cad_feature_id")
        feature = part.get_feature(feature_id) if feature_id else None
        if feature is None:
            feature = next(
                (item for item in reversed(part.features) if not item.suppressed),
                None,
            )
        ui = scene.parametric_cad_ui
        source_sketch = None
        if isinstance(feature, SketchFeature):
            source_sketch = feature
        elif isinstance(feature, (ExtrudeFeature, RevolveFeature)):
            source_sketch = part.get_feature(feature.sketch_id)
        if isinstance(source_sketch, SketchFeature):
            from .sketch import _begin_edit

            try:
                _begin_edit(context, part, source_sketch, False)
            except Exception as exc:
                self.report({"ERROR"}, f"Cannot enter source Sketch: {exc}")
                return {"CANCELLED"}
        elif feature is not None:
            from .part import _set_active_feature

            _set_active_feature(ui, feature)
            ui.panel_tab = "MODEL"
            if getattr(feature, "feature_type", None) in BODY_FEATURE_TYPES:
                _activate_feature_tool(context, feature.feature_type)
        else:
            self.report({"WARNING"}, "This Part Studio has no editable CAD history yet.")
            return {"CANCELLED"}
        tag_redraw()
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_validate_document(bpy.types.Operator):
    bl_idname = "parametric_cad.validate_document"
    bl_label = "Validate CAD Document"
    bl_description = "Check CAD history, dependencies, Sketches, and generated results"
    bl_options = {"REGISTER"}

    def execute(self, context):
        diagnostics = validate_cad_document(context.scene)
        if diagnostics:
            self.report({"WARNING"}, diagnostics[0])
            for message in diagnostics[1:]:
                self.report({"WARNING"}, message)
            return {"FINISHED"}
        self.report({"INFO"}, "CAD document validation passed.")
        return {"FINISHED"}


def _activate_feature_tool(context, kind: str) -> None:
    """Select the matching native toolbar tool when a Model button is used."""

    area = getattr(context, "area", None)
    if area is None or area.type != "VIEW_3D":
        return
    region = next(
        (item for item in getattr(area, "regions", ()) if item.type == "WINDOW"),
        None,
    )
    if region is None:
        return
    try:
        with context.temp_override(
            area=area,
            region=region,
            space_data=getattr(area, "spaces", None).active,
        ):
            bpy.ops.wm.tool_set_by_id(name=f"parametric_cad.feature_{kind.lower()}")
    except (AttributeError, RuntimeError, TypeError):
        # The toolbar is optional and can be unavailable while a workspace is
        # changing; the operator still leaves the feature context selected.
        pass


class PARAMETRIC_CAD_OT_open_feature_tools(bpy.types.Operator):
    """Open one contextual body-feature create/edit tool."""

    bl_idname = "parametric_cad.open_feature_tools"
    bl_label = "Open Feature Tools"
    bl_description = "Open the selected Sketch or body feature's next operation"
    bl_options = {"REGISTER"}

    feature_kind: bpy.props.StringProperty(options={"HIDDEN"})

    def execute(self, context):
        scene = context.scene
        ui = getattr(scene, "parametric_cad_ui", None)
        if ui is None:
            self.report({"ERROR"}, "Enable Blender Parametric CAD first.")
            return {"CANCELLED"}
        try:
            document = load_document_from_scene(scene)
        except CadDocumentError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        part = document.active_part
        selected = part.get_feature(ui.active_feature_id) if part else None
        kind = str(self.feature_kind or "").upper()
        if kind not in {"EXTRUDE", "REVOLVE", "TRANSFORM", "MIRROR"}:
            self.report({"ERROR"}, "Unknown body feature tool.")
            return {"CANCELLED"}
        editing = getattr(selected, "feature_type", None) == kind
        if not editing and kind in {"EXTRUDE", "REVOLVE"} and not isinstance(
            selected, SketchFeature
        ):
            self.report({"ERROR"}, "Select a Sketch feature first.")
            return {"CANCELLED"}
        if not editing and kind in {"TRANSFORM", "MIRROR"} and (
            part is None or previous_body_feature(part) is None
        ):
            self.report(
                {"ERROR"},
                f"{kind.title()} requires an earlier body feature.",
            )
            return {"CANCELLED"}
        # The Model panel is the canonical create/edit surface.  Switching
        # here keeps the parameters visible even when the command was started
        # from the Sketch page or the native left toolbar.
        ui.panel_tab = "MODEL"
        # A matching selected feature is edited in place; a Sketch/body source
        # opens a create form.  Both forms live in the native toolbar settings.
        if not editing:
            if kind == "REVOLVE":
                ui.revolve_operation = "NEW"
                ui.revolve_axis_type = "DATUM_AXIS"
                ui.revolve_axis = "Z"
                ui.revolve_axis_reverse = False
                ui.revolve_angle_deg = 360.0
                ui.revolve_axis_sketch_id = ""
            elif kind == "EXTRUDE":
                ui.extrude_operation = "NEW"
                ui.extrude_depth_mode = "BLIND"
            elif kind == "TRANSFORM":
                ui.transform_translate_x_mm = 0.0
                ui.transform_translate_y_mm = 0.0
                ui.transform_translate_z_mm = 0.0
                ui.transform_rotate_x_deg = 0.0
                ui.transform_rotate_y_deg = 0.0
                ui.transform_rotate_z_deg = 0.0
        ui.feature_create_kind = "" if editing else kind
        ui.mode = "FEATURE_EDIT"
        _activate_feature_tool(context, kind)
        tag_redraw()
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_cancel_feature_tools(bpy.types.Operator):
    """Close the contextual feature editor without changing CAD history."""

    bl_idname = "parametric_cad.cancel_feature_tools"
    bl_label = "Cancel"
    bl_description = "Close this feature editor without applying its parameters"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        ui = getattr(getattr(context, "scene", None), "parametric_cad_ui", None)
        return ui is not None and ui.mode == "FEATURE_EDIT"

    def execute(self, context):
        ui = context.scene.parametric_cad_ui
        # Create forms only hold transient UI values until their Create button
        # runs.  Edit forms likewise write the CAD feature only in Apply, so
        # closing the form is a safe, non-destructive operation.
        ui.feature_create_kind = ""
        ui.feature_name = ""
        ui.revolve_axis_sketch_id = ""
        ui.panel_tab = "MODEL"
        ui.mode = "IDLE"
        tag_redraw()
        return {"FINISHED"}


def _draw_object_context_menu(self, context):
    obj = getattr(getattr(context, "view_layer", None), "objects", None)
    active = getattr(obj, "active", None)
    if active is not None and active.get("cad_generated"):
        self.layout.separator()
        self.layout.operator(
            PARAMETRIC_CAD_OT_edit_cad_history.bl_idname,
            text="Edit CAD History",
            icon="GREASEPENCIL",
        )


_KEYMAP_ITEMS = []
_MENU_REGISTERED = False


def register_keymaps() -> None:
    global _MENU_REGISTERED
    if not _MENU_REGISTERED:
        bpy.types.VIEW3D_MT_object_context_menu.append(_draw_object_context_menu)
        _MENU_REGISTERED = True
    keyconfigs = getattr(getattr(bpy.context, "window_manager", None), "keyconfigs", None)
    keyconfig = getattr(keyconfigs, "addon", None) if keyconfigs else None
    if keyconfig is None:
        return
    keymap = keyconfig.keymaps.new(name="3D View", space_type="VIEW_3D")
    for operator_id in (
        "parametric_cad.edit_cad_history",
        "parametric_cad.edit_sketch_geometry",
    ):
        item = keymap.keymap_items.new(operator_id, "LEFTMOUSE", "DOUBLE_CLICK")
        _KEYMAP_ITEMS.append((keymap, item))


def unregister_keymaps() -> None:
    global _MENU_REGISTERED
    if _MENU_REGISTERED:
        bpy.types.VIEW3D_MT_object_context_menu.remove(_draw_object_context_menu)
        _MENU_REGISTERED = False
    for keymap, item in _KEYMAP_ITEMS:
        try:
            keymap.keymap_items.remove(item)
        except (ReferenceError, RuntimeError):
            pass
    _KEYMAP_ITEMS.clear()


CLASSES = (
    PARAMETRIC_CAD_OT_edit_cad_history,
    PARAMETRIC_CAD_OT_open_feature_tools,
    PARAMETRIC_CAD_OT_cancel_feature_tools,
    PARAMETRIC_CAD_OT_validate_document,
)
