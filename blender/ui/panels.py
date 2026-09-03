"""3D View N-panel for the parametric Part Studio workflow."""

from __future__ import annotations

import json

import bpy

from ...core.references import TopoReference
from ...sketch.sketch import SketchFeature
from ...sketch.numeric import arc_parameters, circle_parameters, rectangle_parameters
from ..adapter import CadDocumentError, load_document_from_scene
from .feature_tree import draw_feature_tree, draw_selected_feature


_PANEL_TITLES = {
    "MODEL": "Model",
    "SKETCH": "Sketch",
    "FEATURES": "Features",
    "OUTPUT": "Output",
}
_PANEL_ICONS = {
    "MODEL": "MESH_CUBE",
    "SKETCH": "GREASEPENCIL",
    "FEATURES": "MOD_SOLIDIFY",
    "OUTPUT": "EXPORT",
}


def _draw_section_navigation(layout, ui):
    """Draw a compact icon rail and return the selected section column."""

    navigation = layout.row(align=True)
    rail = navigation.column(align=True)
    rail.ui_units_x = 2.4
    rail.prop(ui, "panel_tab", text="", expand=True, icon_only=True)
    content = navigation.column(align=True)
    content.label(
        text=_PANEL_TITLES.get(ui.panel_tab, "Model"),
        icon=_PANEL_ICONS.get(ui.panel_tab, "MESH_CUBE"),
    )
    return content


class PARAMETRIC_CAD_PT_main(bpy.types.Panel):
    bl_label = "Parametric CAD"
    bl_idname = "PARAMETRIC_CAD_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "CAD"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        scene = context.scene
        ui = getattr(scene, "parametric_cad_ui", None)
        if ui is None:
            layout.label(text="Blender Parametric CAD is not enabled", icon="ERROR")
            layout.label(text="Enable the extension, then reopen this file.")
            return

        try:
            document = load_document_from_scene(scene)
        except CadDocumentError as exc:
            layout.label(text="CAD document could not be loaded", icon="ERROR")
            layout.label(text=str(exc))
            return

        studio = layout.box()
        studio.label(text="Part Studio", icon="MESH_CUBE")
        row = studio.row(align=True)
        row.prop(ui, "active_part_id", text="")
        row.operator("parametric_cad.new_part", text="", icon="ADD")
        part = document.active_part
        if part is None:
            studio.label(text="Create a Part Studio to begin.", icon="INFO")
            return
        runtime_error = scene.get("parametric_cad_runtime_error")
        if runtime_error:
            error = layout.box()
            error.alert = True
            error.label(text="CAD status", icon="ERROR")
            error.label(text=str(runtime_error))
        active_object = getattr(context.view_layer.objects, "active", None)
        if active_object is not None and active_object.get("cad_generated"):
            warning = layout.box()
            warning.label(text="Generated result mesh (read-only)", icon="LOCKED")
            warning.label(text="Edit CAD History to change the source Sketch/Feature.")
            warning.operator(
                "parametric_cad.edit_cad_history",
                text="Edit CAD History",
                icon="GREASEPENCIL",
            )
        content = _draw_section_navigation(layout, ui)
        if ui.panel_tab == "SKETCH":
            _draw_sketch_section(content, context, part, ui)
        elif ui.panel_tab == "FEATURES":
            _draw_features_section(content, part, ui)
        elif ui.panel_tab == "OUTPUT":
            _draw_output_section(content, part, ui)
        else:
            _draw_model_section(content, part, ui)


def _draw_mcp_service(layout, scene, ui):
    """Expose the one-window service toggle in the same Blender UI being edited."""

    service = layout
    service.label(text="Current Blender window", icon="LINKED")
    try:
        from ...mcp.blender_worker import embedded_service_info

        info = embedded_service_info()
    except (ImportError, RuntimeError):
        info = None
    if info:
        service.label(
            text=f"Running on {info['host']}:{info['port']}",
            icon="CHECKMARK",
        )
        service.operator(
            "parametric_cad.stop_mcp_service",
            text="Stop Service",
            icon="PAUSE",
        )
        return

    service.prop(ui, "mcp_service_port", text="Port")
    service.operator(
        "parametric_cad.start_mcp_service",
        text="Start Service in This Window",
        icon="PLAY",
    )
    if scene.get("parametric_cad_mcp_service"):
        service.label(
            text="Service state was restored; click Start to reconnect.",
            icon="INFO",
        )
    else:
        service.label(
            text="MCP will reuse this window after the service starts.",
            icon="INFO",
        )


class PARAMETRIC_CAD_PT_mcp_service(bpy.types.Panel):
    bl_label = "CAD MCP Service"
    bl_idname = "PARAMETRIC_CAD_PT_mcp_service"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "CAD"
    bl_parent_id = "PARAMETRIC_CAD_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return getattr(context.scene, "parametric_cad_ui", None) is not None

    def draw(self, context):
        _draw_mcp_service(
            self.layout,
            context.scene,
            context.scene.parametric_cad_ui,
        )


def _draw_model_section(layout, part, ui):
    controls = layout.box()
    controls.label(text="Part Studio", icon="MESH_CUBE")
    row = controls.row(align=True)
    row.operator("parametric_cad.rename_part", text="Rename", icon="GREASEPENCIL")
    delete = row.operator("parametric_cad.delete_part", text="Delete", icon="TRASH")
    delete.part_id = part.id
    controls.prop(ui, "show_sketches")

    layout.separator()
    layout.label(text="Feature History")
    draw_feature_tree(layout, part, ui.active_feature_id)
    history = layout.box()
    history.label(text="History", icon="TRACKING_BACKWARDS_SINGLE")
    selected = part.get_feature(ui.active_feature_id)
    if selected is None:
        history.label(text="Select a feature to set the rollback point.", icon="INFO")
    else:
        history.label(text=f"Selected: {selected.name}", icon="DOT")
        history.operator(
            "parametric_cad.rollback_here",
            text="Rollback Here",
            icon="TRACKING_BACKWARDS_SINGLE",
        )
    if part.rollback_index is not None:
        history.label(
            text=f"Rolled back after feature {part.rollback_index + 1}",
            icon="PAUSE",
        )
        history.operator(
            "parametric_cad.roll_forward",
            text="Roll Forward to End",
            icon="TRACKING_FORWARDS_SINGLE",
        )


def _draw_sketch_section(layout, context, part, ui):
    if ui.mode == "SKETCH_EDIT":
        _draw_sketch_editor(layout, context)
        return

    support = layout.box()
    support.label(text="Viewport Selection", icon="RESTRICT_SELECT_OFF")
    support.label(
        text="Supported: New Extrude START/END faces and line-based SIDE faces",
        icon="INFO",
    )
    support.operator("parametric_cad.select_face", icon="FACESEL")
    if ui.selected_face_reference:
        try:
            face = TopoReference.from_dict(json.loads(ui.selected_face_reference))
            source = part.get_feature(face.feature_id)
            source_name = source.name if source is not None else face.feature_id[:8]
            label = f"{source_name} {face.role.replace('_', ' ').title()}"
            support.label(text=label, icon="CHECKMARK")
            if face.role == "SIDE_FACE" and face.source_entity_id:
                support.label(
                    text=f"Source SketchLine: {face.source_entity_id[:8]}",
                    icon="IPO_LINEAR",
                )
        except (TypeError, ValueError, KeyError):
            support.label(text="Invalid face selection", icon="ERROR")

    create = layout.box()
    create.label(text="Create Sketch", icon="OUTLINER_OB_CURVE")
    if ui.selected_face_reference:
        create.label(text="New Sketch will use the selected face.", icon="MESH_PLANE")
    create.prop(ui, "new_sketch_reference", text="")
    create.prop(ui, "new_sketch_offset_mm", text="Plane Offset (mm)")
    create.operator("parametric_cad.new_sketch", icon="OUTLINER_OB_CURVE")


def _draw_features_section(layout, part, ui):
    layout.label(text="Body Features", icon="MOD_SOLIDIFY")

    transform = layout.box()
    transform_header = transform.row(align=True)
    transform_header.label(text="Transform", icon="OBJECT_ORIGIN")
    transform.prop(ui, "transform_translate_x_mm", text="Translate X (mm)")
    transform.prop(ui, "transform_translate_y_mm", text="Translate Y (mm)")
    transform.prop(ui, "transform_translate_z_mm", text="Translate Z (mm)")
    transform.prop(ui, "transform_rotate_x_deg", text="Rotate X (deg)")
    transform.prop(ui, "transform_rotate_y_deg", text="Rotate Y (deg)")
    transform.prop(ui, "transform_rotate_z_deg", text="Rotate Z (deg)")
    transform.operator(
        "parametric_cad.transform",
        text="Add Transform",
        icon="OBJECT_ORIGIN",
    )

    layout.separator()
    mirror = layout.box()
    mirror_header = mirror.row(align=True)
    mirror_header.label(text="Mirror", icon="MOD_MIRROR")
    mirror.prop(ui, "mirror_source_feature_id", text="Source Feature")
    mirror.prop(ui, "mirror_plane_reference", text="Mirror Plane")
    mirror.prop(ui, "mirror_plane_offset_mm", text="Plane Offset (mm)")
    mirror.operator(
        "parametric_cad.mirror",
        text="Add Mirror",
        icon="MOD_MIRROR",
    )

    selected = part.get_feature(ui.active_feature_id)
    if selected is None:
        layout.separator()
        layout.label(text="Select a feature in the Model tab to edit it.", icon="INFO")
    elif ui.mode != "SKETCH_EDIT":
        layout.separator()
        layout.label(text="Selected Feature", icon="RESTRICT_SELECT_OFF")
        draw_selected_feature(layout, selected, ui, part)


def _draw_output_section(layout, part, ui):
    layout.operator(
        "parametric_cad.validate_document",
        text="Validate CAD Document",
        icon="CHECKMARK",
    )
    export = layout.box()
    export.label(text="Export Part Studio", icon="EXPORT")
    export.prop(ui, "export_format", text="Format")
    export.prop(ui, "export_filepath", text="Path")
    export_operator = export.operator(
        "parametric_cad.export_part", text="Export Active Part", icon="EXPORT"
    )
    export_operator.part_id = part.id
    export_operator.file_format = ui.export_format
    export_operator.filepath = ui.export_filepath


def _draw_sketch_editor(layout, context):
    layout.use_property_split = True
    layout.use_property_decorate = False
    ui = context.scene.parametric_cad_ui
    try:
        document = load_document_from_scene(context.scene)
    except CadDocumentError as exc:
        layout.label(text="CAD document could not be loaded", icon="ERROR")
        layout.label(text=str(exc))
        return
    part = document.active_part
    sketch = part.get_feature(ui.active_sketch_id) if part else None
    if not isinstance(sketch, SketchFeature):
        layout.label(text="Active sketch unavailable", icon="ERROR")
        return

    reference = sketch.plane_reference
    plane_label = (
        f"{reference.datum_plane}"
        if reference.reference_type == "DATUM"
        else f"Face {reference.role.replace('_', ' ').title()}"
        if reference.reference_type == "FACE"
        else "Feature End Plane"
    )
    layout.label(text=f"Editing {sketch.name} ({plane_label})")
    layout.prop(ui, "sketch_plane_offset_mm", text="Plane Offset (mm)")
    snap_help = layout.box()
    snap_help.label(text="Snap enabled", icon="SNAP_ON")
    snap_help.label(text="Orange = snap point  •  Green = active target")
    tools = layout.box()
    tools.label(text="Geometry Tools", icon="TOOL_SETTINGS")
    row = tools.row(align=True)
    row.operator("parametric_cad.select_tool", text="Select", icon="RESTRICT_SELECT_OFF")
    row.operator("parametric_cad.draw_line", text="Line", icon="IPO_LINEAR")
    row = tools.row(align=True)
    row.operator("parametric_cad.draw_rectangle", text="Rectangle", icon="MESH_PLANE")
    row.operator("parametric_cad.draw_circle", text="Circle", icon="MESH_CIRCLE")
    row = tools.row(align=True)
    row.operator("parametric_cad.draw_arc", text="Arc", icon="CURVE_BEZCURVE")

    cleanup = layout.box()
    cleanup.label(text="Geometry Cleanup", icon="X")
    row = cleanup.row(align=True)
    row.operator("parametric_cad.delete_region", text="Delete Region", icon="X")
    if ui.active_sketch_entity_id and any(
        entity.id == ui.active_sketch_entity_id for entity in sketch.entities
    ):
        delete_selected = row.operator(
            "parametric_cad.delete_geometry",
            text="Delete Selected",
            icon="X",
        )
        delete_selected.selected_only = True
    row.operator("parametric_cad.delete_geometry", text="Delete Geometry", icon="TRASH")
    coordinates = layout.box()
    coordinates.label(text="Local Sketch Coordinates")
    coordinates.label(text=f"X: {ui.mouse_x_mm:.2f} mm")
    coordinates.label(text=f"Y: {ui.mouse_y_mm:.2f} mm")
    dimensions = layout.box()
    entity_id = ui.active_sketch_entity_id
    try:
        selected_entity_ids = json.loads(ui.active_sketch_entity_ids or "[]")
    except (TypeError, ValueError):
        selected_entity_ids = []
    selected_circles = [
        entity
        for entity in sketch.entities
        if entity.id in selected_entity_ids and entity.entity_type == "CIRCLE"
    ]
    if len(selected_circles) >= 2:
        dimensions.label(
            text=f"Circle group: {len(selected_circles)} selected",
            icon="GROUP",
        )
    if entity_id:
        selected_entity = next(
            (entity for entity in sketch.entities if entity.id == entity_id), None
        )
        if selected_entity is not None:
            dimensions.label(
                text=f"Selected: {selected_entity.entity_type.title()}",
                icon="RESTRICT_SELECT_OFF",
            )
    if rectangle_parameters(sketch, entity_id) is not None:
        dimensions.label(text="Rectangle Dimensions")
        dimensions.prop(ui, "rectangle_x_mm", text="X (mm)")
        dimensions.prop(ui, "rectangle_y_mm", text="Y (mm)")
        dimensions.prop(ui, "rectangle_width_mm", text="Width (mm)")
        dimensions.prop(ui, "rectangle_height_mm", text="Height (mm)")
        dimensions.operator(
            "parametric_cad.numeric_rectangle",
            text="Apply & Rebuild Rectangle",
            icon="FILE_REFRESH",
        )
    elif circle_parameters(sketch, entity_id) is not None:
        dimensions.label(text="Circle Dimensions")
        dimensions.prop(ui, "circle_x_mm", text="Center X (mm)")
        dimensions.prop(ui, "circle_y_mm", text="Center Y (mm)")
        dimensions.prop(ui, "circle_diameter_mm", text="Diameter (mm)")
        dimensions.operator(
            "parametric_cad.numeric_circle",
            text="Apply & Rebuild Circle",
            icon="FILE_REFRESH",
        )
        if len(selected_circles) >= 2:
            dimensions.operator(
                "parametric_cad.numeric_circle_group",
                text="Apply Group Diameter",
                icon="GROUP",
            )
    elif arc_parameters(sketch, entity_id) is not None:
        dimensions.label(text="Arc Dimensions")
        dimensions.prop(ui, "arc_x_mm", text="Center X (mm)")
        dimensions.prop(ui, "arc_y_mm", text="Center Y (mm)")
        dimensions.prop(ui, "arc_radius_mm", text="Radius (mm)")
        dimensions.prop(ui, "arc_start_deg", text="Start (deg)")
        dimensions.prop(ui, "arc_end_deg", text="End (deg)")
        dimensions.operator(
            "parametric_cad.numeric_arc",
            text="Apply & Rebuild Arc",
            icon="FILE_REFRESH",
        )
    else:
        dimensions.label(text="Dimensions")
        dimensions.label(
            text=(
                "Select a Rectangle, Circle, or Arc to edit dimensions."
                if not entity_id
                else "Selected geometry has no numeric dimensions."
            ),
            icon="INFO",
        )
    if sketch.deleted_regions:
        dimensions.label(
            text=f"Deleted regions: {len(sketch.deleted_regions)} (outer edges hidden)",
            icon="X",
        )
    if ui.sketch_dirty:
        dirty = layout.box()
        dirty.alert = True
        dirty.label(text="Sketch changes are not rebuilt yet", icon="TIME")
        dirty.operator(
            "parametric_cad.apply_sketch",
            text="Apply & Rebuild",
            icon="FILE_REFRESH",
        )
    layout.operator(
        "parametric_cad.clear_sketch",
        text="Delete All Sketch Geometry",
        icon="TRASH",
    )
    layout.separator()
    row = layout.row(align=True)
    row.operator("parametric_cad.finish_sketch", icon="CHECKMARK")
    row.operator("parametric_cad.cancel_sketch", icon="X")


class PARAMETRIC_CAD_PT_sketch_tools(bpy.types.Panel):
    bl_label = "Sketch Tools"
    bl_idname = "PARAMETRIC_CAD_PT_sketch_tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "CAD"
    bl_parent_id = "PARAMETRIC_CAD_PT_main"

    @classmethod
    def poll(cls, context):
        ui = getattr(context.scene, "parametric_cad_ui", None)
        return ui is not None and ui.mode == "SKETCH_EDIT" and ui.panel_tab != "SKETCH"

    def draw(self, context):
        _draw_sketch_editor(self.layout, context)


CLASSES = (
    PARAMETRIC_CAD_PT_main,
    PARAMETRIC_CAD_PT_mcp_service,
    PARAMETRIC_CAD_PT_sketch_tools,
)
