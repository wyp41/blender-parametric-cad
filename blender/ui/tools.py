"""Optional CAD tools shown in Blender's left 3D View toolbar."""

from __future__ import annotations

import bpy
from bpy.types import WorkSpaceTool


class _CADSketchTool(WorkSpaceTool):
    """Base class for tools that arm one modal Sketch operator."""

    bl_space_type = "VIEW_3D"
    bl_context_mode = "OBJECT"
    bl_widget = None


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
    bl_icon = "ops.mesh.primitive_plane_add"
    bl_keymap = (
        ("parametric_cad.draw_line", {"type": "LEFTMOUSE", "value": "PRESS"}, None),
    )


class PARAMETRIC_CAD_WST_rectangle(_CADSketchTool):
    bl_idname = "parametric_cad.sketch_rectangle"
    bl_label = "CAD Sketch Rectangle"
    bl_description = "Draw a parametric Sketch rectangle"
    bl_icon = "ops.mesh.primitive_plane_add"
    bl_keymap = (
        ("parametric_cad.draw_rectangle", {"type": "LEFTMOUSE", "value": "PRESS"}, None),
    )


class PARAMETRIC_CAD_WST_circle(_CADSketchTool):
    bl_idname = "parametric_cad.sketch_circle"
    bl_label = "CAD Sketch Circle"
    bl_description = "Draw a parametric Sketch circle"
    bl_icon = "ops.mesh.primitive_circle_add"
    bl_keymap = (
        ("parametric_cad.draw_circle", {"type": "LEFTMOUSE", "value": "PRESS"}, None),
    )


class PARAMETRIC_CAD_WST_arc(_CADSketchTool):
    bl_idname = "parametric_cad.sketch_arc"
    bl_label = "CAD Sketch Arc"
    bl_description = "Draw a three-click center/start/end Sketch arc"
    bl_icon = "ops.curve.primitive_bezier_curve_add"
    bl_keymap = (
        ("parametric_cad.draw_arc", {"type": "LEFTMOUSE", "value": "PRESS"}, None),
    )


class PARAMETRIC_CAD_WST_delete_region(_CADSketchTool):
    bl_idname = "parametric_cad.sketch_delete_region"
    bl_label = "CAD Delete Region"
    bl_description = "Select a bounded Sketch region to remove from profiles"
    bl_icon = "ops.mesh.delete"
    bl_keymap = (
        ("parametric_cad.delete_region", {"type": "LEFTMOUSE", "value": "PRESS"}, None),
    )


class PARAMETRIC_CAD_WST_delete_geometry(_CADSketchTool):
    bl_idname = "parametric_cad.sketch_delete_geometry"
    bl_label = "CAD Delete Geometry"
    bl_description = "Click one Sketch line, circle, or arc to delete it"
    bl_icon = "ops.mesh.delete"
    bl_keymap = (
        ("parametric_cad.delete_geometry", {"type": "LEFTMOUSE", "value": "PRESS"}, None),
    )


TOOL_CLASSES = (
    PARAMETRIC_CAD_WST_select,
    PARAMETRIC_CAD_WST_line,
    PARAMETRIC_CAD_WST_rectangle,
    PARAMETRIC_CAD_WST_circle,
    PARAMETRIC_CAD_WST_arc,
    PARAMETRIC_CAD_WST_delete_region,
    PARAMETRIC_CAD_WST_delete_geometry,
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
                separator=index == 0,
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
