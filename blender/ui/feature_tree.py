"""Compact feature-history drawing helpers for the CAD panel."""

from __future__ import annotations

from ...features.extrude import ExtrudeFeature
from ...sketch.sketch import SketchFeature


def draw_feature_tree(layout, part, active_feature_id: str) -> None:
    box = layout.box()
    box.label(text=part.name, icon="MESH_CUBE")
    origin = box.column(align=True)
    origin.label(text="Origin", icon="OBJECT_ORIGIN")
    for plane in ("XY Plane", "XZ Plane", "YZ Plane"):
        origin.label(text=plane, icon="GRID")
    box.separator()
    for feature in part.features:
        row = box.row(align=True)
        icon = (
            "OUTLINER_OB_CURVE"
            if isinstance(feature, SketchFeature)
            else "MOD_BOOLEAN"
            if isinstance(feature, ExtrudeFeature)
            and feature.operation in {"CUT", "REMOVE"}
            else "MOD_SOLIDIFY"
        )
        operator = row.operator(
            "parametric_cad.select_feature",
            text=feature.name,
            icon=icon,
            depress=feature.id == active_feature_id,
        )
        operator.feature_id = feature.id
        if feature.status == "ERROR":
            row.label(text="", icon="ERROR")
        elif feature.status == "SUPPRESSED":
            row.label(text="", icon="HIDE_ON")
        elif feature.status == "NOT_EVALUATED":
            row.label(text="", icon="PAUSE")


def draw_selected_feature(layout, feature, ui, part) -> None:
    if isinstance(feature, SketchFeature):
        box = layout.box()
        reference = feature.plane_reference
        if reference.reference_type == "DATUM":
            plane_label = f"{reference.datum_plane} Plane"
        else:
            source = part.get_feature(reference.feature_id)
            source_name = source.name if source else "Missing Feature"
            plane_label = f"{source_name} End Plane"
        box.label(text=f"{feature.name} — {plane_label}")
        box.label(text=f"Entities: {len(feature.entities)}")
        box.operator("parametric_cad.edit_sketch", icon="GREASEPENCIL")
        box.separator()
        box.prop(ui, "extrude_operation")
        box.prop(ui, "extrude_depth_mode")
        if ui.extrude_depth_mode == "BLIND":
            box.prop(ui, "extrude_distance_mm", text="Distance (mm)")
        box.operator("parametric_cad.extrude", icon="MOD_SOLIDIFY")
    elif isinstance(feature, ExtrudeFeature):
        box = layout.box()
        icon = (
            "MOD_BOOLEAN"
            if feature.operation in {"CUT", "REMOVE"}
            else "MOD_SOLIDIFY"
        )
        box.label(text=feature.name, icon=icon)
        box.prop(ui, "extrude_operation")
        box.prop(ui, "extrude_depth_mode")
        if ui.extrude_depth_mode == "BLIND":
            box.prop(ui, "extrude_distance_mm", text="Distance (mm)")
        box.operator("parametric_cad.apply_extrude", icon="FILE_REFRESH")
        if feature.status == "ERROR" and feature.error_message:
            error = box.box()
            error.alert = True
            error.label(text=feature.error_message, icon="ERROR")

    commands = layout.box()
    commands.label(text="Feature Actions")
    row = commands.row(align=True)
    row.operator("parametric_cad.rename_feature", text="Rename", icon="GREASEPENCIL")
    row.operator("parametric_cad.delete_feature", text="Delete", icon="TRASH")
    commands.operator("parametric_cad.rollback_here", icon="TRACKING_BACKWARDS_SINGLE")
    if part.rollback_index is not None:
        commands.operator("parametric_cad.roll_forward", icon="TRACKING_FORWARDS_SINGLE")
    commands.operator(
        "parametric_cad.toggle_suppression",
        text="Unsuppress Feature" if feature.suppressed else "Suppress Feature",
        icon="HIDE_OFF" if feature.suppressed else "HIDE_ON",
    )
