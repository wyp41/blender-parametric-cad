"""Safe entry points from disposable result meshes back into CAD history."""

from __future__ import annotations

import bpy

from ...features.extrude import ExtrudeFeature
from ...features.revolve import RevolveFeature
from ...core.part import previous_body_feature
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
            ui.active_feature_id = feature.id
            ui.active_sketch_id = ""
            ui.active_sketch_entity_id = ""
            ui.active_sketch_entity_ids = "[]"
            ui.mode = "FEATURE_EDIT"
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


class PARAMETRIC_CAD_OT_open_feature_tools(bpy.types.Operator):
    """Open one contextual body-feature creation form from the Model page."""

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
        if kind in {"EXTRUDE", "REVOLVE"} and not isinstance(
            selected, SketchFeature
        ):
            self.report({"ERROR"}, "Select a Sketch feature first.")
            return {"CANCELLED"}
        if kind in {"TRANSFORM", "MIRROR"} and (
            part is None or previous_body_feature(part) is None
        ):
            self.report(
                {"ERROR"},
                f"{kind.title()} requires an earlier body feature.",
            )
            return {"CANCELLED"}
        ui.feature_create_kind = kind
        # Keep the current workspace.  Model buttons render the form inline,
        # while a toolbar tool renders the same controls beside its icon.
        ui.mode = "FEATURE_EDIT"
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
    PARAMETRIC_CAD_OT_validate_document,
)
