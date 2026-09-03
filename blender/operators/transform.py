"""Transform and Mirror history feature operators."""

from __future__ import annotations

from math import radians

import bpy

from ...core.part import previous_body_feature
from ...features.extrude import ExtrudeFeature
from ...features.mirror import MirrorFeature
from ...features.revolve import RevolveFeature
from ...features.transform import TransformFeature
from ...sketch.plane import SketchPlaneReference
from ..adapter import load_document_from_scene, rebuild_part, save_document_to_scene


def _report_rebuild(operator, result) -> bool:
    if result.success:
        return True
    message = result.errors[0].message if result.errors else "Part rebuild failed"
    operator.report({"ERROR"}, message)
    return False


def _transform_values(ui) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    return (
        (
            ui.transform_translate_x_mm / 1000.0,
            ui.transform_translate_y_mm / 1000.0,
            ui.transform_translate_z_mm / 1000.0,
        ),
        (
            radians(ui.transform_rotate_x_deg),
            radians(ui.transform_rotate_y_deg),
            radians(ui.transform_rotate_z_deg),
        ),
    )


def _mirror_plane(ui) -> SketchPlaneReference:
    tokens = str(ui.mirror_plane_reference or "DATUM|YZ").split("|")
    if len(tokens) == 2 and tokens[0] == "DATUM":
        return SketchPlaneReference(
            "DATUM",
            datum_plane=tokens[1],
            offset=ui.mirror_plane_offset_mm / 1000.0,
        )
    if len(tokens) == 3 and tokens[0] == "FEATURE":
        return SketchPlaneReference(
            "FEATURE_PLANE",
            datum_plane=None,
            feature_id=tokens[1],
            role=tokens[2],
            offset=ui.mirror_plane_offset_mm / 1000.0,
        )
    raise ValueError("Select a valid datum or semantic mirror plane.")


def _mirror_dependencies(part, source_id: str, before_index: int | None = None) -> list[str]:
    source = part.get_feature(source_id)
    if not isinstance(source, (ExtrudeFeature, RevolveFeature)) or source.operation != "ADD":
        raise ValueError("Mirror source must be an additive Extrude or Revolve feature.")
    index = len(part.features) if before_index is None else before_index
    if part.get_feature_index(source_id) is None or part.get_feature_index(source_id) >= index:
        raise ValueError("Mirror source must be an earlier feature.")
    dependencies = [source.id]
    previous = previous_body_feature(part, index)
    if previous is not None and previous.id not in dependencies:
        dependencies.append(previous.id)
    return dependencies


class PARAMETRIC_CAD_OT_transform(bpy.types.Operator):
    bl_idname = "parametric_cad.transform"
    bl_label = "Transform"
    bl_description = "Add a parametric rigid Transform to the current body"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        ui = scene.parametric_cad_ui
        document = load_document_from_scene(scene)
        part = document.active_part
        previous = previous_body_feature(part) if part else None
        if part is None or previous is None:
            self.report({"ERROR"}, "Transform requires an earlier body feature.")
            return {"CANCELLED"}
        translation, rotation = _transform_values(ui)
        feature = TransformFeature(
            name=part.next_feature_name("Transform"),
            translation=translation,
            rotation=rotation,
            dependencies=[previous.id],
        )
        part.add_feature(feature)
        ui.active_feature_id = feature.id
        ui.feature_name = feature.name
        ui.feature_create_kind = ""
        ui.active_sketch_id = ""
        ui.mode = "FEATURE_EDIT"
        save_document_to_scene(scene, document)
        _report_rebuild(self, rebuild_part(scene, part.id))
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_apply_transform(bpy.types.Operator):
    bl_idname = "parametric_cad.apply_transform"
    bl_label = "Apply Transform"
    bl_description = "Update Transform parameters and rebuild the Part Studio"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        ui = scene.parametric_cad_ui
        document = load_document_from_scene(scene)
        part = document.active_part
        feature = part.get_feature(ui.active_feature_id) if part else None
        if not isinstance(feature, TransformFeature):
            self.report({"ERROR"}, "Select a Transform feature.")
            return {"CANCELLED"}
        feature.translation, feature.rotation = _transform_values(ui)
        previous = previous_body_feature(part, part.get_feature_index(feature.id))
        feature.dependencies = [previous.id] if previous is not None else []
        save_document_to_scene(scene, document)
        _report_rebuild(self, rebuild_part(scene, part.id))
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_mirror(bpy.types.Operator):
    bl_idname = "parametric_cad.mirror"
    bl_label = "Mirror"
    bl_description = "Mirror one additive Extrude or Revolve feature across a CAD plane"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        ui = scene.parametric_cad_ui
        document = load_document_from_scene(scene)
        part = document.active_part
        if part is None:
            self.report({"ERROR"}, "Create a Part Studio first.")
            return {"CANCELLED"}
        source_id = str(ui.mirror_source_feature_id or "")
        try:
            dependencies = _mirror_dependencies(part, source_id)
            plane = _mirror_plane(ui)
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        feature = MirrorFeature(
            name=part.next_feature_name("Mirror"),
            source_feature_id=source_id,
            mirror_plane=plane,
            dependencies=dependencies,
        )
        part.add_feature(feature)
        ui.active_feature_id = feature.id
        ui.feature_name = feature.name
        ui.feature_create_kind = ""
        ui.active_sketch_id = ""
        ui.mode = "FEATURE_EDIT"
        save_document_to_scene(scene, document)
        _report_rebuild(self, rebuild_part(scene, part.id))
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_apply_mirror(bpy.types.Operator):
    bl_idname = "parametric_cad.apply_mirror"
    bl_label = "Apply Mirror"
    bl_description = "Update Mirror source/plane and rebuild the Part Studio"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        ui = scene.parametric_cad_ui
        document = load_document_from_scene(scene)
        part = document.active_part
        feature = part.get_feature(ui.active_feature_id) if part else None
        if not isinstance(feature, MirrorFeature):
            self.report({"ERROR"}, "Select a Mirror feature.")
            return {"CANCELLED"}
        source_id = str(ui.mirror_source_feature_id or "")
        try:
            dependencies = _mirror_dependencies(
                part, source_id, part.get_feature_index(feature.id)
            )
            plane = _mirror_plane(ui)
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        feature.source_feature_id = source_id
        feature.mirror_plane = plane
        feature.dependencies = dependencies
        save_document_to_scene(scene, document)
        _report_rebuild(self, rebuild_part(scene, part.id))
        return {"FINISHED"}


CLASSES = (
    PARAMETRIC_CAD_OT_transform,
    PARAMETRIC_CAD_OT_apply_transform,
    PARAMETRIC_CAD_OT_mirror,
    PARAMETRIC_CAD_OT_apply_mirror,
)
