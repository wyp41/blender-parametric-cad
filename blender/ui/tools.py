"""Optional CAD tools shown in Blender's left 3D View toolbar."""

from __future__ import annotations

import bpy
from bpy.types import WorkSpaceTool

from ...core.part import BODY_FEATURE_TYPES
from ...sketch.sketch import SketchFeature
from ..adapter import CadDocumentError, load_document_from_scene


class _CADSketchTool(WorkSpaceTool):
    """Base class for tools that arm one modal Sketch operator."""

    bl_space_type = "VIEW_3D"
    bl_context_mode = "OBJECT"
    bl_widget = None

    @classmethod
    def poll(cls, context):
        ui = getattr(getattr(context, "scene", None), "parametric_cad_ui", None)
        return ui is not None and ui.mode == "SKETCH_EDIT"

    @staticmethod
    def draw_settings(_context, layout, _tool):
        layout.label(text="Click in the 3D View; the first click starts this tool.")


class _CADMeasureTool(WorkSpaceTool):
    """Base class for the point-to-point CAD measurement tool."""

    bl_space_type = "VIEW_3D"
    bl_context_mode = "OBJECT"
    bl_widget = None

    @classmethod
    def poll(cls, context):
        return getattr(getattr(context, "scene", None), "parametric_cad_ui", None) is not None

    @staticmethod
    def draw_settings(context, layout, _tool):
        _draw_measure_settings(context, layout)


class _CADFeatureTool(WorkSpaceTool):
    """Base class for contextual post-Sketch feature tools."""

    bl_space_type = "VIEW_3D"
    bl_context_mode = "OBJECT"
    bl_widget = None
    feature_kind = ""

    @classmethod
    def poll(cls, context):
        ui = getattr(getattr(context, "scene", None), "parametric_cad_ui", None)
        if ui is None or ui.mode == "SKETCH_EDIT":
            return False
        try:
            document = load_document_from_scene(context.scene)
        except (CadDocumentError, AttributeError, TypeError, ValueError):
            return False
        part = document.active_part
        selected = part.get_feature(ui.active_feature_id) if part else None
        selected_type = getattr(selected, "feature_type", None)
        if cls.feature_kind in {"EXTRUDE", "REVOLVE"}:
            return isinstance(selected, SketchFeature) or selected_type == cls.feature_kind
        return selected_type in BODY_FEATURE_TYPES

    @staticmethod
    def draw_settings(_context, layout, _tool):
        layout.label(text="Click in the 3D View to open this feature editor.")


def _draw_measure_settings(context, layout) -> None:
    """Keep measurement controls beside the active toolbar icon."""

    layout.use_property_split = True
    layout.use_property_decorate = False
    ui = getattr(getattr(context, "scene", None), "parametric_cad_ui", None)
    if ui is None:
        layout.label(text="Enable Blender Parametric CAD first.", icon="ERROR")
        return
    layout.label(text="Click two CAD points in the viewport.", icon="DRIVER_DISTANCE")
    layout.prop(ui, "measure_snap_tolerance_px", text="Snap (px)")
    if ui.measure_pending:
        layout.label(text="First point set; click the second point.", icon="DOT")
    elif ui.measure_has_result:
        layout.label(
            text=f"Last distance: {ui.measure_distance_mm:.2f} mm",
            icon="DRIVER_DISTANCE",
        )
    row = layout.row(align=True)
    row.operator("parametric_cad.measure", text="Start / Reset", icon="DRIVER_DISTANCE")
    row.operator("parametric_cad.clear_measurement", text="Clear", icon="X")


class PARAMETRIC_CAD_WST_measure(_CADMeasureTool):
    bl_idname = "parametric_cad.measure_tool"
    bl_label = "CAD Measure"
    bl_description = "Measure true 3D distance between two snapped CAD points"
    bl_icon = "ops.view3d.ruler"
    bl_keymap = (
        ("parametric_cad.measure", {"type": "LEFTMOUSE", "value": "PRESS"}, None),
    )


def _draw_feature_settings(context, layout, kind: str) -> None:
    """Render a feature's create/edit parameters in Blender's tool settings.

    Unlike a normal N-panel section, this layout is owned by the active
    toolbar icon.  It therefore stays beside the icon for both new features
    and edits to an existing selected history item.
    """

    layout.use_property_split = True
    layout.use_property_decorate = False
    ui = getattr(getattr(context, "scene", None), "parametric_cad_ui", None)
    if ui is None:
        layout.label(text="Enable Blender Parametric CAD first.", icon="ERROR")
        return
    try:
        document = load_document_from_scene(context.scene)
    except (CadDocumentError, AttributeError, TypeError, ValueError) as exc:
        layout.label(text=str(exc), icon="ERROR")
        return
    part = document.active_part
    selected = part.get_feature(ui.active_feature_id) if part else None
    if selected is None:
        layout.label(text="Select a CAD Sketch or body feature first.", icon="INFO")
        return
    editing = getattr(selected, "feature_type", None) == kind
    panel = layout.box()

    # Keep the context at the top of the popover.  The native toolbar gives
    # feature settings only a narrow column, so a separate line for each item
    # is much easier to read than two properties competing for one row.
    panel.label(
        text=f"{'Edit' if editing else 'Create'} {kind.title()}",
        icon="TOOL_SETTINGS" if editing else "ADD",
    )
    panel.label(
        text=f"Object: {selected.name}",
        icon="OUTLINER_OB_MESH" if editing else "LINKED",
    )
    if editing:
        panel.prop(ui, "feature_name", text="Name")
        rename = panel.operator(
            "parametric_cad.rename_feature",
            text="Rename",
            icon="GREASEPENCIL",
        )
        rename.feature_id = selected.id
        rename.name = ui.feature_name or selected.name
        if selected.status in {"ERROR", "BLOCKED"} and selected.error_message:
            error = panel.box()
            error.alert = True
            error.label(text=selected.error_message, icon="ERROR")
    else:
        source_label = "Source Sketch" if kind in {"EXTRUDE", "REVOLVE"} else "Source Body"
        panel.label(text=f"{source_label}: {selected.name}", icon="LINKED")

    form = panel.column(align=True)
    if kind == "EXTRUDE":
        form.prop(ui, "extrude_operation", text="Operation")
        form.prop(ui, "extrude_depth_mode", text="Extent")
        if ui.extrude_depth_mode == "BLIND":
            form.prop(ui, "extrude_distance_mm", text="Distance (mm)")
        action_id = "parametric_cad.apply_extrude" if editing else "parametric_cad.extrude"
        action_icon = "FILE_REFRESH" if editing else "MOD_SOLIDIFY"
    elif kind == "REVOLVE":
        form.prop(ui, "revolve_operation", text="Operation")
        form.prop(ui, "revolve_angle_deg", text="Angle (deg)")
        form.prop(ui, "revolve_axis_type", text="Axis Type")
        if ui.revolve_axis_type == "DATUM_AXIS":
            form.prop(ui, "revolve_axis", text="Datum Axis")
        else:
            form.prop(ui, "revolve_axis_line_id", text="Sketch Line")
        form.prop(ui, "revolve_axis_reverse", text="Reverse Axis")
        if ui.revolve_angle_deg >= 359.999:
            form.label(text="Reverse affects partial angles only", icon="INFO")
        action_id = "parametric_cad.apply_revolve" if editing else "parametric_cad.revolve"
        action_icon = "FILE_REFRESH" if editing else "MOD_SCREW"
    elif kind == "TRANSFORM":
        translation = form.box()
        translation.label(text="Translation (mm)", icon="ARROW_LEFTRIGHT")
        translation.prop(ui, "transform_translate_x_mm", text="X")
        translation.prop(ui, "transform_translate_y_mm", text="Y")
        translation.prop(ui, "transform_translate_z_mm", text="Z")
        rotation = form.box()
        rotation.label(text="Rotation (deg)", icon="DRIVER_ROTATIONAL_DIFFERENCE")
        rotation.prop(ui, "transform_rotate_x_deg", text="X")
        rotation.prop(ui, "transform_rotate_y_deg", text="Y")
        rotation.prop(ui, "transform_rotate_z_deg", text="Z")
        action_id = "parametric_cad.apply_transform" if editing else "parametric_cad.transform"
        action_icon = "FILE_REFRESH" if editing else "OBJECT_ORIGIN"
    elif kind == "MIRROR":
        form.prop(ui, "mirror_source_feature_id", text="Source Feature")
        form.prop(ui, "mirror_plane_reference", text="Mirror Plane")
        form.prop(ui, "mirror_plane_offset_mm", text="Offset (mm)")
        action_id = "parametric_cad.apply_mirror" if editing else "parametric_cad.mirror"
        action_icon = "FILE_REFRESH" if editing else "MOD_MIRROR"
    else:
        panel.label(text="Unsupported feature tool.", icon="ERROR")
        return

    # Keep the commit and exit controls visible in the same toolbar popover.
    # They are full-width on purpose: Blender otherwise ellipsizes the action
    # label when the selected left-toolbar icon is shown in a narrow region.
    panel.separator(factor=0.4)
    panel.operator(
        action_id,
        text="Apply & Rebuild" if editing else f"Create {kind.title()}",
        icon=action_icon,
    )
    panel.operator(
        "parametric_cad.cancel_feature_tools",
        text="Cancel",
        icon="CANCEL",
    )


class PARAMETRIC_CAD_WST_select(_CADSketchTool):
    bl_idname = "parametric_cad.sketch_select"
    bl_label = "CAD Sketch Select"
    bl_description = "Select Sketch geometry and show its dimensions"
    bl_icon = "ops.generic.select_box"
    bl_keymap = (
        ("parametric_cad.select_tool", {"type": "LEFTMOUSE", "value": "PRESS"}, None),
    )


class PARAMETRIC_CAD_WST_line(_CADSketchTool):
    bl_idname = "parametric_cad.sketch_line"
    bl_label = "CAD Sketch Line"
    bl_description = "Draw a Sketch line or split a boundary"
    bl_icon = "ops.gpencil.draw.line"
    bl_keymap = (
        ("parametric_cad.draw_line", {"type": "LEFTMOUSE", "value": "PRESS"}, None),
    )


class PARAMETRIC_CAD_WST_rectangle(_CADSketchTool):
    bl_idname = "parametric_cad.sketch_rectangle"
    bl_label = "CAD Sketch Rectangle"
    bl_description = "Draw a parametric Sketch rectangle"
    bl_icon = "ops.gpencil.primitive_box"
    bl_keymap = (
        ("parametric_cad.draw_rectangle", {"type": "LEFTMOUSE", "value": "PRESS"}, None),
    )


class PARAMETRIC_CAD_WST_circle(_CADSketchTool):
    bl_idname = "parametric_cad.sketch_circle"
    bl_label = "CAD Sketch Circle"
    bl_description = "Draw a parametric Sketch circle"
    bl_icon = "ops.gpencil.primitive_circle"
    bl_keymap = (
        ("parametric_cad.draw_circle", {"type": "LEFTMOUSE", "value": "PRESS"}, None),
    )


class PARAMETRIC_CAD_WST_arc(_CADSketchTool):
    bl_idname = "parametric_cad.sketch_arc"
    bl_label = "CAD Sketch Arc"
    bl_description = "Draw a three-click center/start/end Sketch arc"
    bl_icon = "ops.gpencil.primitive_arc"
    bl_keymap = (
        ("parametric_cad.draw_arc", {"type": "LEFTMOUSE", "value": "PRESS"}, None),
    )


class PARAMETRIC_CAD_WST_delete_region(_CADSketchTool):
    bl_idname = "parametric_cad.sketch_delete_region"
    bl_label = "CAD Delete Region"
    bl_description = "Select a bounded Sketch region to remove from profiles"
    bl_icon = "ops.gpencil.stroke_trim"
    bl_keymap = (
        ("parametric_cad.delete_region", {"type": "LEFTMOUSE", "value": "PRESS"}, None),
    )


class PARAMETRIC_CAD_WST_delete_geometry(_CADSketchTool):
    bl_idname = "parametric_cad.sketch_delete_geometry"
    bl_label = "CAD Delete Geometry"
    bl_description = "Click one Sketch line, circle, or arc to delete it"
    bl_icon = "ops.gpencil.draw.eraser"
    bl_keymap = (
        ("parametric_cad.delete_geometry", {"type": "LEFTMOUSE", "value": "PRESS"}, None),
    )


class PARAMETRIC_CAD_WST_extrude(_CADFeatureTool):
    bl_idname = "parametric_cad.feature_extrude"
    bl_label = "CAD Extrude"
    bl_description = "Open the Extrude editor for the selected Sketch"
    bl_icon = "ops.mesh.extrude_region_move"
    feature_kind = "EXTRUDE"

    @staticmethod
    def draw_settings(context, layout, _tool):
        _draw_feature_settings(context, layout, "EXTRUDE")
    bl_keymap = (
        (
            "parametric_cad.open_feature_tools",
            {"type": "LEFTMOUSE", "value": "PRESS"},
            {"properties": [("feature_kind", "EXTRUDE")]},
        ),
    )


class PARAMETRIC_CAD_WST_revolve(_CADFeatureTool):
    bl_idname = "parametric_cad.feature_revolve"
    bl_label = "CAD Revolve"
    bl_description = "Open the Revolve editor for the selected Sketch"
    bl_icon = "ops.mesh.spin"
    feature_kind = "REVOLVE"

    @staticmethod
    def draw_settings(context, layout, _tool):
        _draw_feature_settings(context, layout, "REVOLVE")
    bl_keymap = (
        (
            "parametric_cad.open_feature_tools",
            {"type": "LEFTMOUSE", "value": "PRESS"},
            {"properties": [("feature_kind", "REVOLVE")]},
        ),
    )


class PARAMETRIC_CAD_WST_transform(_CADFeatureTool):
    bl_idname = "parametric_cad.feature_transform"
    bl_label = "CAD Transform"
    bl_description = "Open the Transform editor for the selected body feature"
    bl_icon = "ops.transform.translate"
    feature_kind = "TRANSFORM"

    @staticmethod
    def draw_settings(context, layout, _tool):
        _draw_feature_settings(context, layout, "TRANSFORM")
    bl_keymap = (
        (
            "parametric_cad.open_feature_tools",
            {"type": "LEFTMOUSE", "value": "PRESS"},
            {"properties": [("feature_kind", "TRANSFORM")]},
        ),
    )


class PARAMETRIC_CAD_WST_mirror(_CADFeatureTool):
    bl_idname = "parametric_cad.feature_mirror"
    bl_label = "CAD Mirror"
    bl_description = "Open the Mirror editor for the selected body feature"
    bl_icon = "ops.transform.transform"
    feature_kind = "MIRROR"

    @staticmethod
    def draw_settings(context, layout, _tool):
        _draw_feature_settings(context, layout, "MIRROR")
    bl_keymap = (
        (
            "parametric_cad.open_feature_tools",
            {"type": "LEFTMOUSE", "value": "PRESS"},
            {"properties": [("feature_kind", "MIRROR")]},
        ),
    )


TOOL_CLASSES = (
    PARAMETRIC_CAD_WST_measure,
    PARAMETRIC_CAD_WST_select,
    PARAMETRIC_CAD_WST_line,
    PARAMETRIC_CAD_WST_rectangle,
    PARAMETRIC_CAD_WST_circle,
    PARAMETRIC_CAD_WST_arc,
    PARAMETRIC_CAD_WST_delete_region,
    PARAMETRIC_CAD_WST_delete_geometry,
    PARAMETRIC_CAD_WST_extrude,
    PARAMETRIC_CAD_WST_revolve,
    PARAMETRIC_CAD_WST_transform,
    PARAMETRIC_CAD_WST_mirror,
)

FEATURE_TOOL_CLASSES = (
    PARAMETRIC_CAD_WST_extrude,
    PARAMETRIC_CAD_WST_revolve,
    PARAMETRIC_CAD_WST_transform,
    PARAMETRIC_CAD_WST_mirror,
)

SKETCH_TOOL_CLASSES = (
    PARAMETRIC_CAD_WST_select,
    PARAMETRIC_CAD_WST_line,
    PARAMETRIC_CAD_WST_rectangle,
    PARAMETRIC_CAD_WST_circle,
    PARAMETRIC_CAD_WST_arc,
    PARAMETRIC_CAD_WST_delete_region,
    PARAMETRIC_CAD_WST_delete_geometry,
)

_registered_tools = []
_toolbar_registered = False


def register() -> None:
    """Register only the tools for the current CAD editing stage."""

    global _registered_tools, _toolbar_registered
    _registered_tools = []
    _toolbar_registered = True
    refresh_toolbar()


def refresh_toolbar(context=None) -> None:
    """Swap Sketch and body tools when the CAD mode changes.

    Blender 5.1 copies a WorkSpaceTool class into a static ToolDef and does
    not call a class-level ``poll`` while drawing the toolbar.  Re-registering
    the small stage-specific group is therefore the reliable way to keep
    Sketch tools out of the finished-body workflow (and vice versa).
    """

    global _registered_tools
    if not _toolbar_registered:
        return
    scene = getattr(context, "scene", None) if context is not None else getattr(bpy.context, "scene", None)
    ui = getattr(scene, "parametric_cad_ui", None)
    stage = getattr(ui, "mode", "IDLE") if ui is not None else "IDLE"
    desired = [PARAMETRIC_CAD_WST_measure]
    if stage == "SKETCH_EDIT":
        desired.extend(SKETCH_TOOL_CLASSES)
    elif stage == "FEATURE_EDIT":
        desired.extend(FEATURE_TOOL_CLASSES)

    for tool in reversed(list(_registered_tools)):
        if tool in desired:
            continue
        try:
            bpy.utils.unregister_tool(tool)
        except (RuntimeError, TypeError, AttributeError):
            pass
        _registered_tools.remove(tool)

    for index, tool in enumerate(desired):
        if tool in _registered_tools:
            continue
        try:
            if index == 0:
                after = {"builtin.primitive_cube_add"}
            else:
                previous = next(
                    (
                        candidate
                        for candidate in reversed(desired[:index])
                        if candidate in _registered_tools
                    ),
                    None,
                )
                after = {previous.bl_idname} if previous is not None else None
            bpy.utils.register_tool(
                tool,
                after=after,
                separator=index == 0 or index == 1,
            )
        except Exception as exc:  # Blender version/reload may already own a tool.
            print(f"Parametric CAD toolbar tool {tool.bl_idname!r} unavailable: {exc}")
            continue
        _registered_tools.append(tool)


def unregister() -> None:
    global _toolbar_registered
    for tool in reversed(_registered_tools):
        try:
            bpy.utils.unregister_tool(tool)
        except (RuntimeError, TypeError, AttributeError):
            pass
    _registered_tools.clear()
    _toolbar_registered = False
