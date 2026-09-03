"""Compact feature-history and contextual editor drawing helpers."""

from __future__ import annotations

from ...features.extrude import ExtrudeFeature
from ...features.mirror import MirrorFeature
from ...features.revolve import RevolveFeature
from ...features.transform import TransformFeature
from ...sketch.sketch import SketchFeature


def draw_feature_tree(layout, part, active_feature_id: str) -> None:
    """Draw the persistent history as a compact, selectable tree."""

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
        elif isinstance(feature, TransformFeature):
            icon = "OBJECT_ORIGIN"
        elif isinstance(feature, MirrorFeature):
            icon = "MOD_MIRROR"
        operator = row.operator(
            "parametric_cad.select_feature",
            text=feature.name,
            icon=icon,
            depress=feature.id == active_feature_id,
        )
        operator.feature_id = feature.id
        if isinstance(feature, SketchFeature):
            edit = row.operator(
                "parametric_cad.edit_sketch",
                text="",
                icon="GREASEPENCIL",
            )
            edit.feature_id = feature.id
        if feature.status == "ERROR":
            row.label(text="", icon="ERROR")
        elif feature.status == "BLOCKED":
            row.label(text="", icon="CANCEL")
        elif feature.status == "SUPPRESSED":
            row.label(text="", icon="HIDE_ON")
        elif feature.status == "NOT_EVALUATED":
            row.label(text="", icon="PAUSE")


def _panel(layout, panel_id: str, title: str, icon: str, default_closed: bool = True):
    """Create a Blender 5.1 collapsible panel and return its body."""

    header, body = layout.panel(panel_id, default_closed=default_closed)
    header.label(text=title, icon=icon)
    return body


def _draw_error(body, feature) -> None:
    if feature.status not in {"ERROR", "BLOCKED"} or not feature.error_message:
        return
    error = body.box()
    error.alert = True
    error.label(text=feature.error_message, icon="ERROR")


def draw_feature_actions(layout, feature) -> None:
    """Draw full-width actions for the currently selected history feature."""

    commands = layout.box()
    commands.label(text=f"Feature Actions — {feature.name}", icon="TOOL_SETTINGS")
    if isinstance(feature, SketchFeature):
        edit = commands.operator(
            "parametric_cad.edit_sketch",
            text="Edit Sketch",
            icon="GREASEPENCIL",
        )
        edit.feature_id = feature.id
    commands.operator(
        "parametric_cad.rename_feature",
        text="Rename Feature",
        icon="GREASEPENCIL",
    )
    commands.operator(
        "parametric_cad.delete_feature",
        text="Delete Feature",
        icon="TRASH",
    )
    commands.operator(
        "parametric_cad.toggle_suppression",
        text="Unsuppress Feature" if feature.suppressed else "Suppress Feature",
        icon="HIDE_OFF" if feature.suppressed else "HIDE_ON",
    )


def _draw_sketch_feature_editor(body, feature, ui, part) -> None:
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
    body.label(text=f"Support: {plane_label}", icon="MESH_PLANE")
    body.label(text=f"Entities: {len(feature.entities)}", icon="OUTLINER_OB_CURVE")
    body.prop(ui, "sketch_plane_offset_mm", text="Plane Offset (mm)")
    body.operator(
        "parametric_cad.apply_sketch",
        text="Apply Offset & Rebuild",
        icon="FILE_REFRESH",
    )
    if feature.deleted_regions:
        body.label(text=f"Deleted regions: {len(feature.deleted_regions)}", icon="X")


def _draw_extrude_form(
    body, ui, operator_id: str, action_label: str, icon: str = "MOD_SOLIDIFY"
) -> None:
    body.prop(ui, "extrude_operation", text="Operation")
    body.prop(ui, "extrude_depth_mode", text="Extent")
    if ui.extrude_depth_mode == "BLIND":
        body.prop(ui, "extrude_distance_mm", text="Distance (mm)")
    body.operator(operator_id, text=action_label, icon=icon)


def _draw_revolve_form(body, ui, operator_id: str, action_label: str) -> None:
    body.prop(ui, "revolve_operation", text="Operation")
    body.prop(ui, "revolve_axis_type", text="Axis")
    if ui.revolve_axis_type == "DATUM_AXIS":
        body.prop(ui, "revolve_axis", text="Datum Axis")
    else:
        body.prop(ui, "revolve_axis_line_id", text="Sketch Line")
    body.prop(ui, "revolve_axis_reverse", text="Reverse Axis")
    body.prop(ui, "revolve_angle_deg", text="Angle (deg)")
    if ui.revolve_angle_deg >= 359.999:
        body.label(text="Reverse affects partial angles only", icon="INFO")
    body.operator(operator_id, text=action_label, icon="MOD_SCREW")


def _draw_transform_form(body, ui, operator_id: str, action_label: str) -> None:
    translation = _panel(
        body,
        "cad_transform_translation",
        "Translation",
        "ARROW_LEFTRIGHT",
        default_closed=False,
    )
    if translation is not None:
        translation.prop(ui, "transform_translate_x_mm", text="X (mm)")
        translation.prop(ui, "transform_translate_y_mm", text="Y (mm)")
        translation.prop(ui, "transform_translate_z_mm", text="Z (mm)")
    rotation = _panel(
        body,
        "cad_transform_rotation",
        "Rotation",
        "DRIVER_ROTATIONAL_DIFFERENCE",
        default_closed=True,
    )
    if rotation is not None:
        rotation.prop(ui, "transform_rotate_x_deg", text="X (deg)")
        rotation.prop(ui, "transform_rotate_y_deg", text="Y (deg)")
        rotation.prop(ui, "transform_rotate_z_deg", text="Z (deg)")
    body.operator(operator_id, text=action_label, icon="OBJECT_ORIGIN")


def _draw_mirror_form(body, ui, operator_id: str, action_label: str) -> None:
    body.prop(ui, "mirror_source_feature_id", text="Source Feature")
    body.prop(ui, "mirror_plane_reference", text="Mirror Plane")
    body.prop(ui, "mirror_plane_offset_mm", text="Plane Offset (mm)")
    body.operator(operator_id, text=action_label, icon="MOD_MIRROR")


def draw_selected_feature(layout, feature, ui, part) -> None:
    """Draw only the editor for the selected history feature.

    Creation forms are intentionally kept in the Model page's contextual
    ``Next Feature`` card.  This prevents all Transform/Mirror/Revolve fields
    from occupying the panel when the user is only inspecting a Sketch or a
    different feature.
    """

    if isinstance(feature, SketchFeature):
        body = _panel(
            layout,
            f"cad_editor_{feature.id}",
            f"{feature.name} — Sketch",
            "OUTLINER_OB_CURVE",
            default_closed=False,
        )
        if body is not None:
            _draw_sketch_feature_editor(body, feature, ui, part)
    elif isinstance(feature, ExtrudeFeature):
        body = _panel(
            layout,
            f"cad_editor_{feature.id}",
            f"{feature.name} — Extrude",
            "MOD_BOOLEAN"
            if feature.operation in {"CUT", "REMOVE"}
            else "MOD_SOLIDIFY",
            default_closed=False,
        )
        if body is not None:
            _draw_extrude_form(
                body,
                ui,
                "parametric_cad.apply_extrude",
                "Apply & Rebuild",
            )
            _draw_error(body, feature)
    elif isinstance(feature, RevolveFeature):
        body = _panel(
            layout,
            f"cad_editor_{feature.id}",
            f"{feature.name} — Revolve",
            "MOD_SCREW",
            default_closed=False,
        )
        if body is not None:
            _draw_revolve_form(
                body,
                ui,
                "parametric_cad.apply_revolve",
                "Apply & Rebuild",
            )
            _draw_error(body, feature)
    elif isinstance(feature, TransformFeature):
        body = _panel(
            layout,
            f"cad_editor_{feature.id}",
            f"{feature.name} — Transform",
            "OBJECT_ORIGIN",
            default_closed=False,
        )
        if body is not None:
            _draw_transform_form(
                body,
                ui,
                "parametric_cad.apply_transform",
                "Apply & Rebuild",
            )
            _draw_error(body, feature)
    elif isinstance(feature, MirrorFeature):
        body = _panel(
            layout,
            f"cad_editor_{feature.id}",
            f"{feature.name} — Mirror",
            "MOD_MIRROR",
            default_closed=False,
        )
        if body is not None:
            _draw_mirror_form(
                body,
                ui,
                "parametric_cad.apply_mirror",
                "Apply & Rebuild",
            )
            _draw_error(body, feature)

    draw_feature_actions(layout, feature)
