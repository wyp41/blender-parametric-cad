"""Viewport-driven Chamfer and Fillet feature operators."""

from __future__ import annotations

import json

import bpy

from ...core.part import previous_body_feature
from ...core.serialization import edge_reference_from_dict
from ...features.chamfer import ChamferFeature
from ...features.fillet import FilletFeature
from ..adapter import load_document_from_scene, rebuild_part, save_document_to_scene


def _selected_edge_references(ui):
    try:
        values = json.loads(ui.selected_edge_references or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(values, list):
        return []
    return [edge_reference_from_dict(value) for value in values if isinstance(value, dict)]


def _edge_dependencies(part, references):
    previous = previous_body_feature(part)
    dependencies = [previous.id] if previous is not None else []
    for reference in references:
        if reference.producer_feature_id not in dependencies:
            dependencies.append(reference.producer_feature_id)
    return dependencies


def _commit_edge_feature(context, feature_type: str) -> set[str]:
    document = load_document_from_scene(context.scene)
    part = document.active_part
    ui = context.scene.parametric_cad_ui
    if part is None:
        raise ValueError("Create a Part Studio first.")
    selected = part.get_feature(ui.active_feature_id)
    references = _selected_edge_references(ui)
    editing = (
        selected
        if selected is not None and selected.feature_type == feature_type
        else None
    )
    if editing is None and not references:
        raise ValueError("Select at least one supported straight edge first.")

    if feature_type == "CHAMFER":
        amount = float(ui.chamfer_distance_mm) / 1000.0
        if editing is not None:
            editing.edge_references = references or editing.edge_references
            editing.distance = amount
            editing.dependencies = _edge_dependencies(part, editing.edge_references)
            feature = editing
        else:
            feature = ChamferFeature(
                name=part.next_feature_name("Chamfer"),
                edge_references=references,
                distance=amount,
                dependencies=_edge_dependencies(part, references),
            )
    else:
        amount = float(ui.fillet_radius_mm) / 1000.0
        if editing is not None:
            editing.edge_references = references or editing.edge_references
            editing.radius = amount
            editing.dependencies = _edge_dependencies(part, editing.edge_references)
            feature = editing
        else:
            feature = FilletFeature(
                name=part.next_feature_name("Fillet"),
                edge_references=references,
                radius=amount,
                dependencies=_edge_dependencies(part, references),
            )
    if editing is None:
        part.add_feature(feature)
    save_document_to_scene(context.scene, document)
    result = rebuild_part(context.scene, part.id)
    ui.active_feature_id = feature.id
    ui.feature_name = feature.name
    ui.feature_create_kind = ""
    ui.mode = "FEATURE_EDIT"
    if result.success:
        return set()
    return {error.message for error in result.errors}


class PARAMETRIC_CAD_OT_create_chamfer(bpy.types.Operator):
    bl_idname = "parametric_cad.chamfer"
    bl_label = "Create Chamfer"
    bl_description = "Create or rebuild an equal-distance chamfer on selected persistent edges"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            errors = _commit_edge_feature(context, "CHAMFER")
        except (TypeError, ValueError, KeyError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if errors:
            self.report({"WARNING"}, next(iter(errors)))
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_create_fillet(bpy.types.Operator):
    bl_idname = "parametric_cad.fillet"
    bl_label = "Create Fillet"
    bl_description = "Create or rebuild a constant-radius fillet on selected persistent edges"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            errors = _commit_edge_feature(context, "FILLET")
        except (TypeError, ValueError, KeyError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if errors:
            self.report({"WARNING"}, next(iter(errors)))
        return {"FINISHED"}


CLASSES = (PARAMETRIC_CAD_OT_create_chamfer, PARAMETRIC_CAD_OT_create_fillet)
