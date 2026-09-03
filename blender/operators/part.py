"""Part creation and feature-history selection operators."""

from __future__ import annotations

from math import degrees

import bpy

from ...core.document import CadDocument
from ...core.part import Part
from ...core.part import delete_feature, get_recursive_dependents
from ...features.extrude import ExtrudeFeature
from ...features.mirror import MirrorFeature
from ...features.revolve import RevolveFeature
from ...features.transform import TransformFeature
from ...sketch.sketch import SketchFeature
from ..adapter import (
    load_document_from_scene,
    rebuild_part,
    remove_part_geometry,
    rename_part_geometry,
    save_document_to_scene,
)


def _next_part_studio_name(document: CadDocument) -> str:
    number = len(document.parts) + 1
    existing = {part.name for part in document.parts}
    while f"Part Studio {number}" in existing:
        number += 1
    return f"Part Studio {number}"


def _set_active_feature(ui, feature) -> None:
    # Selecting a history row always closes any pending creation form.  The
    # matching toolbar tool then reflects only the selected source/feature.
    ui.feature_create_kind = ""
    ui.active_feature_id = feature.id if feature else ""
    ui.feature_name = feature.name if feature else ""
    ui.active_sketch_id = feature.id if isinstance(feature, SketchFeature) else ""
    ui.active_sketch_entity_id = ""
    ui.active_sketch_entity_ids = "[]"
    ui.sketch_dirty = False
    ui.sketch_applied_signature = ""
    ui.mode = "FEATURE_EDIT" if feature else "IDLE"
    if isinstance(feature, ExtrudeFeature):
        ui.extrude_distance_mm = feature.distance * 1000.0
        ui.extrude_operation = "REMOVE" if feature.operation == "CUT" else feature.operation
        ui.extrude_depth_mode = feature.depth_mode
        if feature.operation == "NEW" and feature.status == "OK":
            ui.new_sketch_reference = f"FEATURE|{feature.id}|END_PLANE"
    elif isinstance(feature, RevolveFeature):
        ui.revolve_operation = feature.operation
        ui.revolve_angle_deg = degrees(feature.angle)
        ui.revolve_axis_type = feature.axis_reference.reference_type
        ui.revolve_axis_reverse = feature.axis_reference.direction < 0
        if feature.axis_reference.reference_type == "DATUM_AXIS":
            ui.revolve_axis = feature.axis_reference.axis or "Z"
        elif feature.axis_reference.entity_id:
            ui.revolve_axis_line_id = feature.axis_reference.entity_id
    elif isinstance(feature, SketchFeature):
        ui.sketch_plane_offset_mm = feature.plane_offset * 1000.0
    elif isinstance(feature, TransformFeature):
        ui.transform_translate_x_mm = feature.translation[0] * 1000.0
        ui.transform_translate_y_mm = feature.translation[1] * 1000.0
        ui.transform_translate_z_mm = feature.translation[2] * 1000.0
        ui.transform_rotate_x_deg = degrees(feature.rotation[0])
        ui.transform_rotate_y_deg = degrees(feature.rotation[1])
        ui.transform_rotate_z_deg = degrees(feature.rotation[2])
    elif isinstance(feature, MirrorFeature):
        try:
            ui.mirror_source_feature_id = feature.source_feature_id
        except (TypeError, ValueError):
            pass
        reference = feature.mirror_plane
        token = (
            f"DATUM|{reference.datum_plane}"
            if reference.reference_type == "DATUM"
            else f"FEATURE|{reference.feature_id}|{reference.role}"
            if reference.reference_type == "FEATURE_PLANE"
            else "DATUM|YZ"
        )
        try:
            ui.mirror_plane_reference = token
        except (TypeError, ValueError):
            pass
        ui.mirror_plane_offset_mm = reference.offset * 1000.0


class PARAMETRIC_CAD_OT_new_part(bpy.types.Operator):
    bl_idname = "parametric_cad.new_part"
    bl_label = "New Part Studio"
    bl_description = "Create a new single-body Part Studio"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        document = load_document_from_scene(context.scene)
        part = Part(name=_next_part_studio_name(document))
        document.add_part(part)
        save_document_to_scene(context.scene, document)
        ui = context.scene.parametric_cad_ui
        ui.mode = "IDLE"
        ui.active_part_id = part.id
        ui.active_feature_id = ""
        ui.feature_name = ""
        ui.feature_create_kind = ""
        ui.active_sketch_id = ""
        ui.active_sketch_entity_id = ""
        ui.active_sketch_entity_ids = "[]"
        ui.sketch_dirty = False
        ui.sketch_applied_signature = ""
        ui.selected_face_reference = ""
        self.report({"INFO"}, f"Created {part.name}")
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_rename_part(bpy.types.Operator):
    bl_idname = "parametric_cad.rename_part"
    bl_label = "Rename Part Studio"
    bl_options = {"REGISTER", "UNDO"}

    name: bpy.props.StringProperty(name="Name")

    def invoke(self, context, _event):
        part = load_document_from_scene(context.scene).active_part
        if part is None:
            return {"CANCELLED"}
        self.name = part.name
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        document = load_document_from_scene(context.scene)
        part = document.active_part
        name = self.name.strip()
        if part is None or not name:
            self.report({"ERROR"}, "Enter a Part Studio name")
            return {"CANCELLED"}
        part.name = name
        save_document_to_scene(context.scene, document)
        rename_part_geometry(part.id, part.name)
        ui = context.scene.parametric_cad_ui
        ui.property_unset("active_part_id")
        ui.active_part_id = part.id
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_delete_part(bpy.types.Operator):
    bl_idname = "parametric_cad.delete_part"
    bl_label = "Delete Part Studio"
    bl_options = {"REGISTER", "UNDO"}

    part_id: bpy.props.StringProperty()

    def invoke(self, context, _event):
        document = load_document_from_scene(context.scene)
        part = document.get_part(self.part_id) if self.part_id else document.active_part
        if part is None:
            return {"CANCELLED"}
        self.part_id = part.id
        return context.window_manager.invoke_props_dialog(self, width=380)

    def draw(self, context):
        part = load_document_from_scene(context.scene).get_part(self.part_id)
        if part is not None:
            self.layout.label(text=f"Delete {part.name}?", icon="ERROR")
            self.layout.label(text="Its feature history and generated geometry will be removed.")

    def execute(self, context):
        document = load_document_from_scene(context.scene)
        removed = document.remove_part(self.part_id)
        if removed is None:
            return {"CANCELLED"}
        save_document_to_scene(context.scene, document)
        remove_part_geometry(removed.id)
        ui = context.scene.parametric_cad_ui
        ui.mode = "IDLE"
        ui.active_feature_id = ""
        ui.feature_name = ""
        ui.feature_create_kind = ""
        ui.active_sketch_id = ""
        ui.active_sketch_entity_id = ""
        ui.active_sketch_entity_ids = "[]"
        ui.sketch_dirty = False
        ui.sketch_applied_signature = ""
        ui.selected_face_reference = ""
        ui.active_part_id = document.active_part_id or "NONE"
        self.report({"INFO"}, f"Deleted {removed.name}")
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_select_feature(bpy.types.Operator):
    bl_idname = "parametric_cad.select_feature"
    bl_label = "Select CAD Feature"

    feature_id: bpy.props.StringProperty()

    def execute(self, context):
        document = load_document_from_scene(context.scene)
        part = document.active_part
        feature = part.get_feature(self.feature_id) if part else None
        if feature is None:
            self.report({"ERROR"}, "CAD feature no longer exists")
            return {"CANCELLED"}
        _set_active_feature(context.scene.parametric_cad_ui, feature)
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_rename_feature(bpy.types.Operator):
    bl_idname = "parametric_cad.rename_feature"
    bl_label = "Rename Feature"
    bl_options = {"REGISTER", "UNDO"}

    feature_id: bpy.props.StringProperty()
    name: bpy.props.StringProperty(name="Name")

    def invoke(self, context, _event):
        document = load_document_from_scene(context.scene)
        part = document.active_part
        self.feature_id = context.scene.parametric_cad_ui.active_feature_id
        feature = part.get_feature(self.feature_id) if part else None
        if feature is None:
            return {"CANCELLED"}
        self.name = feature.name
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        document = load_document_from_scene(context.scene)
        part = document.active_part
        feature = part.get_feature(self.feature_id) if part else None
        name = self.name.strip()
        if feature is None or not name:
            self.report({"ERROR"}, "Enter a Feature name")
            return {"CANCELLED"}
        ui = context.scene.parametric_cad_ui
        if name == feature.name:
            if ui.active_feature_id == feature.id:
                ui.feature_name = feature.name
            self.report({"INFO"}, "Feature name is unchanged.")
            return {"FINISHED"}
        feature.name = name
        save_document_to_scene(context.scene, document)
        result = rebuild_part(context.scene, part.id)
        if not result.success and result.errors:
            self.report({"WARNING"}, result.errors[0].message)
        if ui.active_feature_id == feature.id:
            ui.feature_name = name
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_delete_feature(bpy.types.Operator):
    bl_idname = "parametric_cad.delete_feature"
    bl_label = "Delete Feature"
    bl_options = {"REGISTER", "UNDO"}

    feature_id: bpy.props.StringProperty()

    def invoke(self, context, _event):
        document = load_document_from_scene(context.scene)
        part = document.active_part
        self.feature_id = context.scene.parametric_cad_ui.active_feature_id
        if part is None or part.get_feature(self.feature_id) is None:
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self, width=380)

    def draw(self, context):
        document = load_document_from_scene(context.scene)
        part = document.active_part
        feature = part.get_feature(self.feature_id) if part else None
        if feature is None:
            return
        self.layout.label(text=f"Delete {feature.name}?", icon="ERROR")
        dependents = get_recursive_dependents(part, feature.id)
        if dependents:
            self.layout.label(text="The following dependent Features will also be deleted:")
            column = self.layout.column(align=True)
            for dependent_id in dependents:
                dependent = part.get_feature(dependent_id)
                if dependent is not None:
                    column.label(text=dependent.name, icon="DOT")

    def execute(self, context):
        document = load_document_from_scene(context.scene)
        part = document.active_part
        if part is None:
            return {"CANCELLED"}
        index = part.get_feature_index(self.feature_id)
        deleted = delete_feature(part, self.feature_id)
        if not deleted:
            return {"CANCELLED"}
        save_document_to_scene(context.scene, document)
        ui = context.scene.parametric_cad_ui
        selected = None
        if part.features and index is not None:
            selected = part.features[index - 1 if index > 0 else 0]
        _set_active_feature(ui, selected)
        result = rebuild_part(context.scene, part.id)
        if not result.success and result.errors:
            self.report({"WARNING"}, result.errors[0].message)
        self.report({"INFO"}, f"Deleted {len(deleted)} Feature(s)")
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_rollback_here(bpy.types.Operator):
    bl_idname = "parametric_cad.rollback_here"
    bl_label = "Rollback Here"
    bl_description = "Evaluate history only through the selected feature"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        document = load_document_from_scene(context.scene)
        part = document.active_part
        ui = context.scene.parametric_cad_ui
        index = part.get_feature_index(ui.active_feature_id) if part else None
        if part is None or index is None:
            return {"CANCELLED"}
        part.rollback_index = index
        save_document_to_scene(context.scene, document)
        result = rebuild_part(context.scene, part.id)
        if not result.success and result.errors:
            self.report({"WARNING"}, result.errors[0].message)
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_roll_forward(bpy.types.Operator):
    bl_idname = "parametric_cad.roll_forward"
    bl_label = "Roll Forward to End"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        document = load_document_from_scene(context.scene)
        part = document.active_part
        if part is None:
            return {"CANCELLED"}
        part.rollback_index = None
        save_document_to_scene(context.scene, document)
        result = rebuild_part(context.scene, part.id)
        if not result.success and result.errors:
            self.report({"WARNING"}, result.errors[0].message)
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_toggle_suppression(bpy.types.Operator):
    bl_idname = "parametric_cad.toggle_suppression"
    bl_label = "Suppress / Unsuppress Feature"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        document = load_document_from_scene(context.scene)
        part = document.active_part
        ui = context.scene.parametric_cad_ui
        feature = part.get_feature(ui.active_feature_id) if part else None
        if feature is None:
            return {"CANCELLED"}
        feature.suppressed = not feature.suppressed
        save_document_to_scene(context.scene, document)
        result = rebuild_part(context.scene, part.id)
        if not result.success and result.errors:
            self.report({"WARNING"}, result.errors[0].message)
        return {"FINISHED"}


CLASSES = (
    PARAMETRIC_CAD_OT_new_part,
    PARAMETRIC_CAD_OT_rename_part,
    PARAMETRIC_CAD_OT_delete_part,
    PARAMETRIC_CAD_OT_select_feature,
    PARAMETRIC_CAD_OT_rename_feature,
    PARAMETRIC_CAD_OT_delete_feature,
    PARAMETRIC_CAD_OT_rollback_here,
    PARAMETRIC_CAD_OT_roll_forward,
    PARAMETRIC_CAD_OT_toggle_suppression,
)
