"""Per-Part Studio mesh export operators."""

from __future__ import annotations

import bpy
from bpy.props import EnumProperty, StringProperty

from ..adapter import export_part
from ..adapter import load_document_from_scene


class PARAMETRIC_CAD_OT_export_part(bpy.types.Operator):
    """Export exactly one Part Studio's current generated result."""

    bl_idname = "parametric_cad.export_part"
    bl_label = "Export Part"
    bl_description = "Export the selected Part Studio result as STL, OBJ, or PLY"
    bl_options = {"REGISTER"}

    part_id: StringProperty(name="Part Studio", default="", options={"HIDDEN"})
    filepath: StringProperty(name="Filepath", subtype="FILE_PATH", default="")
    file_format: EnumProperty(
        name="Format",
        items=(
            ("STL", "STL", "Export a watertight triangle mesh for fabrication"),
            ("OBJ", "OBJ", "Export an OBJ mesh with an optional MTL sidecar"),
            ("PLY", "PLY", "Export a polygon mesh"),
        ),
        default="STL",
    )

    def invoke(self, context, _event):
        document = load_document_from_scene(context.scene)
        ui = context.scene.parametric_cad_ui
        self.part_id = self.part_id or document.active_part_id or ""
        self.filepath = self.filepath or ui.export_filepath
        self.file_format = self.file_format or ui.export_format
        if not self.part_id:
            self.report({"ERROR"}, "Create a Part Studio first")
            return {"CANCELLED"}
        if not self.filepath:
            context.window_manager.fileselect_add(self)
            return {"RUNNING_MODAL"}
        return self.execute(context)

    def execute(self, context):
        document = load_document_from_scene(context.scene)
        ui = context.scene.parametric_cad_ui
        part_id = self.part_id or document.active_part_id or ""
        filepath = self.filepath or ui.export_filepath
        try:
            exported = export_part(
                context.scene,
                part_id,
                filepath,
                self.file_format or ui.export_format,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        ui.export_filepath = exported
        ui.export_format = self.file_format
        self.report({"INFO"}, f"Exported {exported}")
        return {"FINISHED"}


CLASSES = (PARAMETRIC_CAD_OT_export_part,)
