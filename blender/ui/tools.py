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
    if editing:
        header = layout.box()
        header.label(text=f"Editing {selected.name}", icon="TOOL_SETTINGS")
        identity = header.row(align=True)
        identity.prop(ui, "feature_name", text="Name")
        rename = identity.operator(
            "parametric_cad.rename_feature",
            text="Rename",
            icon="GREASEPENCIL",
        )
        rename.feature_id = selected.id
        rename.name = ui.feature_name or selected.name
        if selected.status in {"ERROR", "BLOCKED"} and selected.error_message:
            error = header.box()
            error.alert = True
            error.label(text=selected.error_message, icon="ERROR")
    else:
        layout.label(text=f"Source: {selected.name}", icon="LINKED")
    if kind == "EXTRUDE":
        layout.prop(ui, "extrude_operation", text="Operation")
        layout.prop(ui, "extrude_depth_mode", text="Extent")
        if ui.extrude_depth_mode == "BLIND":
            layout.prop(ui, "extrude_distance_mm", text="Distance (mm)")
        layout.operator(
            "parametric_cad.apply_extrude" if editing else "parametric_cad.extrude",
            text="Apply & Rebuild" if editing else "Create Extrude",
            icon="FILE_REFRESH" if editing else "MOD_SOLIDIFY",
        )
    elif kind == "REVOLVE":
        layout.prop(ui, "revolve_operation", text="Operation")
        layout.prop(ui, "revolve_axis_type", text="Axis")
        if ui.revolve_axis_type == "DATUM_AXIS":
            layout.prop(ui, "revolve_axis", text="Datum Axis")
        else:
            layout.prop(ui, "revolve_axis_line_id", text="Sketch Line")
        layout.prop(ui, "revolve_axis_reverse", text="Reverse Axis")
        layout.prop(ui, "revolve_angle_deg", text="Angle (deg)")
        layout.operator(
            "parametric_cad.apply_revolve" if editing else "parametric_cad.revolve",
            text="Apply & Rebuild" if editing else "Create Revolve",
            icon="FILE_REFRESH" if editing else "MOD_SCREW",
        )
    elif kind == "TRANSFORM":
        layout.prop(ui, "transform_translate_x_mm", text="Translate X (mm)")
        layout.prop(ui, "transform_translate_y_mm", text="Translate Y (mm)")
        layout.prop(ui, "transform_translate_z_mm", text="Translate Z (mm)")
        layout.prop(ui, "transform_rotate_x_deg", text="Rotate X (deg)")
        layout.prop(ui, "transform_rotate_y_deg", text="Rotate Y (deg)")
        layout.prop(ui, "transform_rotate_z_deg", text="Rotate Z (deg)")
        layout.operator(
            "parametric_cad.apply_transform" if editing else "parametric_cad.transform",
            text="Apply & Rebuild" if editing else "Create Transform",
            icon="FILE_REFRESH" if editing else "OBJECT_ORIGIN",
        )
    elif kind == "MIRROR":
        layout.prop(ui, "mirror_source_feature_id", text="Source Feature")
        layout.prop(ui, "mirror_plane_reference", text="Mirror Plane")
        layout.prop(ui, "mirror_plane_offset_mm", text="Plane Offset (mm)")
        layout.operator(
            "parametric_cad.apply_mirror" if editing else "parametric_cad.mirror",
            text="Apply & Rebuild" if editing else "Create Mirror",
            icon="FILE_REFRESH" if editing else "MOD_MIRROR",
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

_registered_tools = []


def register() -> None:
    """Add CAD tools without making toolbar registration a hard dependency."""

    global _registered_tools
    _registered_tools = []
    for index, tool in enumerate(TOOL_CLASSES):
        try:
            bpy.utils.register_tool(
                tool,
                after={"builtin.primitive_cube_add"} if index == 0 else None,
                separator=index == 0 or tool in FEATURE_TOOL_CLASSES,
            )
        except Exception as exc:  # Blender version/reload may already own a tool.
            print(f"Parametric CAD toolbar tool {tool.bl_idname!r} unavailable: {exc}")
            continue
        _registered_tools.append(tool)


def unregister() -> None:
    for tool in reversed(_registered_tools):
        try:
            bpy.utils.unregister_tool(tool)
        except (RuntimeError, TypeError, AttributeError):
            pass
    _registered_tools.clear()
