"""Compact feature-history drawing helpers for the CAD panel."""

from __future__ import annotations

from ...features.extrude import ExtrudeFeature
from ...features.revolve import RevolveFeature
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
        if isinstance(feature, RevolveFeature):
            icon = "MOD_SCREW"
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
        elif reference.reference_type == "FACE":
            source = part.get_feature(reference.feature_id)
            source_name = source.name if source else "Missing Feature"
            plane_label = f"{source_name} {reference.role.replace('_', ' ').title()}"
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
        _draw_revolve_controls(box, ui, "Create Revolve")
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
    elif isinstance(feature, RevolveFeature):
        box = layout.box()
        box.label(text=feature.name, icon="MOD_SCREW")
        _draw_revolve_controls(box, ui, "Apply Revolve")
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


def _draw_revolve_controls(box, ui, action_label: str) -> None:
    revolve = box.box()
    revolve.label(text="Revolve")
    revolve.prop(ui, "revolve_operation")
    revolve.prop(ui, "revolve_axis_type")
    if ui.revolve_axis_type == "DATUM_AXIS":
        revolve.prop(ui, "revolve_axis")
    else:
        revolve.prop(ui, "revolve_axis_line_id")
    revolve.prop(ui, "revolve_angle_deg")
    operator_id = (
        "parametric_cad.apply_revolve"
        if action_label == "Apply Revolve"
        else "parametric_cad.revolve"
    )
    revolve.operator(operator_id, text=action_label, icon="MOD_SCREW")
