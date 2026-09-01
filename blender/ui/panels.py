"""3D View N-panel for the parametric Part Studio workflow."""

from __future__ import annotations

import json

import bpy

from ...core.references import TopoReference
from ...sketch.sketch import SketchFeature
from ...sketch.numeric import arc_parameters, circle_parameters, rectangle_parameters
from ..adapter import load_document_from_scene
from .feature_tree import draw_feature_tree, draw_selected_feature


class PARAMETRIC_CAD_PT_main(bpy.types.Panel):
    bl_label = "Parametric CAD"
    bl_idname = "PARAMETRIC_CAD_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "CAD"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        ui = scene.parametric_cad_ui
        try:
            document = load_document_from_scene(scene)
        except (ValueError, TypeError) as exc:
            layout.label(text="CAD document could not be loaded", icon="ERROR")
            layout.label(text=str(exc))
            return

        studio = layout.box()
        studio.label(text="Part Studio", icon="MESH_CUBE")
        if document.active_part_id and ui.active_part_id != document.active_part_id:
            ui.active_part_id = document.active_part_id
        row = studio.row(align=True)
        row.prop(ui, "active_part_id", text="")
        row.operator("parametric_cad.new_part", text="", icon="ADD")
        part = document.active_part
        if part is None:
            studio.label(text="Create a Part Studio to begin.", icon="INFO")
            return
        row = studio.row(align=True)
        row.operator("parametric_cad.rename_part", text="Rename", icon="GREASEPENCIL")
        delete = row.operator("parametric_cad.delete_part", text="Delete", icon="TRASH")
        delete.part_id = part.id
        studio.prop(ui, "show_sketches")

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
        create.label(text="Create")
        if ui.selected_face_reference:
            create.label(text="New Sketch will use the selected face.", icon="MESH_PLANE")
        create.prop(ui, "new_sketch_reference", text="")
        create.operator("parametric_cad.new_sketch", icon="OUTLINER_OB_CURVE")

        layout.separator()
        layout.label(text="Feature List")
        draw_feature_tree(layout, part, ui.active_feature_id)
        if part.rollback_index is not None:
            layout.label(text=f"Rolled back after feature {part.rollback_index + 1}", icon="PAUSE")
            layout.operator("parametric_cad.roll_forward", icon="TRACKING_FORWARDS_SINGLE")

        selected = part.get_feature(ui.active_feature_id)
        if selected is not None and ui.mode != "SKETCH_EDIT":
            layout.separator()
            draw_selected_feature(layout, selected, ui, part)


class PARAMETRIC_CAD_PT_sketch_tools(bpy.types.Panel):
    bl_label = "Sketch Tools"
    bl_idname = "PARAMETRIC_CAD_PT_sketch_tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "CAD"
    bl_parent_id = "PARAMETRIC_CAD_PT_main"

    @classmethod
    def poll(cls, context):
        return (
            hasattr(context.scene, "parametric_cad_ui")
            and context.scene.parametric_cad_ui.mode == "SKETCH_EDIT"
        )

    def draw(self, context):
        layout = self.layout
        ui = context.scene.parametric_cad_ui
        document = load_document_from_scene(context.scene)
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
        row = layout.row(align=True)
        row.operator("parametric_cad.select_tool", text="Select", icon="RESTRICT_SELECT_OFF")
        row.operator("parametric_cad.draw_line", text="Line", icon="IPO_LINEAR")
        row = layout.row(align=True)
        row.operator("parametric_cad.draw_rectangle", text="Rectangle", icon="MESH_PLANE")
        row.operator("parametric_cad.draw_circle", text="Circle", icon="MESH_CIRCLE")
        row = layout.row(align=True)
        row.operator("parametric_cad.draw_arc", text="Arc", icon="CURVE_BEZCURVE")
        row.operator(
            "parametric_cad.delete_region",
            text="Delete Region",
            icon="X",
        )
        coordinates = layout.box()
        coordinates.label(text="Local Sketch Coordinates")
        coordinates.label(text=f"X: {ui.mouse_x_mm:.2f} mm")
        coordinates.label(text=f"Y: {ui.mouse_y_mm:.2f} mm")
        dimensions = layout.box()
        entity_id = ui.active_sketch_entity_id
        if rectangle_parameters(sketch, entity_id) is not None:
            dimensions.label(text="Rectangle Dimensions")
            dimensions.prop(ui, "rectangle_x_mm")
            dimensions.prop(ui, "rectangle_y_mm")
            dimensions.prop(ui, "rectangle_width_mm")
            dimensions.prop(ui, "rectangle_height_mm")
            dimensions.operator("parametric_cad.numeric_rectangle", text="Update Rectangle")
        elif circle_parameters(sketch, entity_id) is not None:
            dimensions.label(text="Circle Dimensions")
            dimensions.prop(ui, "circle_x_mm")
            dimensions.prop(ui, "circle_y_mm")
            dimensions.prop(ui, "circle_diameter_mm")
            dimensions.operator("parametric_cad.numeric_circle", text="Update Circle")
        elif arc_parameters(sketch, entity_id) is not None:
            dimensions.label(text="Arc Dimensions")
            dimensions.prop(ui, "arc_x_mm")
            dimensions.prop(ui, "arc_y_mm")
            dimensions.prop(ui, "arc_radius_mm")
            dimensions.prop(ui, "arc_start_deg")
            dimensions.prop(ui, "arc_end_deg")
            dimensions.operator("parametric_cad.numeric_arc", text="Update Arc")
        else:
            dimensions.label(text="Dimensions")
            dimensions.label(
                text="Use Select, then click a Rectangle, Circle, or Arc.",
                icon="INFO",
            )
        if sketch.deleted_regions:
            dimensions.label(
                text=f"Deleted regions: {len(sketch.deleted_regions)}",
                icon="X",
            )
        layout.operator("parametric_cad.clear_sketch", icon="TRASH")
        layout.separator()
        row = layout.row(align=True)
        row.operator("parametric_cad.finish_sketch", icon="CHECKMARK")
        row.operator("parametric_cad.cancel_sketch", icon="X")


CLASSES = (PARAMETRIC_CAD_PT_main, PARAMETRIC_CAD_PT_sketch_tools)
