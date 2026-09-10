"""Blender operators for M9 driving Sketch dimensions."""

from __future__ import annotations

from copy import deepcopy

import bpy

from ...core.references import SketchEntityReference
from ...sketch.dimensions import (
    DIAMETER,
    DISTANCE,
    HORIZONTAL_DISTANCE,
    LENGTH,
    RADIUS,
    VERTICAL_DISTANCE,
    DimensionError,
    SketchDimension,
    dimension_value,
    validate_dimension_conflicts,
)
from ...sketch.entities import SketchCircle, SketchLine
from ...sketch.sketch import SketchFeature
from ...sketch.solver import SketchSolver
from ..adapter import load_document_from_scene, rebuild_part, save_document_to_scene
from ..viewport.sketch_overlay import tag_redraw
from ..viewport.sketch_selection import selected_references
from .sketch import mark_sketch_dirty, sketch_signature


def _active_sketch(context):
    ui = context.scene.parametric_cad_ui
    document = load_document_from_scene(context.scene)
    part = document.active_part
    sketch = part.get_feature(ui.active_sketch_id) if part else None
    if not isinstance(sketch, SketchFeature):
        return document, part, None
    return document, part, sketch


def _fallback_references(ui, sketch: SketchFeature) -> list[SketchEntityReference]:
    if not ui.active_sketch_entity_id:
        return []
    entity = next(
        (item for item in sketch.entities if item.id == ui.active_sketch_entity_id),
        None,
    )
    if entity is None:
        return []
    return [SketchEntityReference(sketch.id, entity.id, "ENTITY")]


def _dimension_type_for_selection(ui, sketch, references):
    kind = str(ui.sketch_dimension_type)
    if len(references) == 1 and kind == DISTANCE:
        entity = next((item for item in sketch.entities if item.id == references[0].entity_id), None)
        if isinstance(entity, SketchLine):
            return LENGTH
        if isinstance(entity, SketchCircle):
            return RADIUS
    if len(references) == 2 and kind not in {
        HORIZONTAL_DISTANCE,
        VERTICAL_DISTANCE,
        DISTANCE,
    }:
        return DISTANCE
    return kind


class PARAMETRIC_CAD_OT_add_dimension(bpy.types.Operator):
    bl_idname = "parametric_cad.add_dimension"
    bl_label = "Add Driving Dimension"
    bl_description = "Add a persistent driving dimension to the selected Sketch entity or points"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ui = context.scene.parametric_cad_ui
        if ui.mode != "SKETCH_EDIT":
            self.report({"ERROR"}, "Enter Sketch Edit before adding a dimension.")
            return {"CANCELLED"}
        document, part, sketch = _active_sketch(context)
        if sketch is None or part is None:
            self.report({"ERROR"}, "The active Sketch is unavailable.")
            return {"CANCELLED"}
        references = selected_references(ui) or _fallback_references(ui, sketch)
        if not references:
            self.report({"ERROR"}, "Select a Sketch entity, endpoint, or center first.")
            return {"CANCELLED"}
        kind = _dimension_type_for_selection(ui, sketch, references)
        if len(references) == 1 and kind in {RADIUS, DIAMETER}:
            entity = next(
                (item for item in sketch.entities if item.id == references[0].entity_id),
                None,
            )
            if isinstance(entity, SketchCircle) and references[0].sub_element == "CENTER":
                references = [SketchEntityReference(sketch.id, entity.id, "ENTITY")]
        dimension = SketchDimension(
            dimension_type=kind,
            entity_refs=references,
            # Use a temporary valid scalar while measuring the current
            # geometry; the stored value is replaced immediately below.
            value=1.0,
            driving=True,
        )
        try:
            dimension.value = dimension_value(sketch, dimension)
            validate_dimension_conflicts(sketch, dimension)
        except DimensionError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        sketch.dimensions.append(dimension)
        ui.active_sketch_dimension_id = dimension.id
        ui.sketch_dimension_type = dimension.dimension_type
        ui.sketch_dimension_value_mm = dimension.value * 1000.0
        save_document_to_scene(context.scene, document)
        mark_sketch_dirty(ui, sketch)
        result = rebuild_part(context.scene, part.id)
        if not result.success:
            sketch.dimensions.remove(dimension)
            save_document_to_scene(context.scene, document)
            ui.active_sketch_dimension_id = ""
            self.report(
                {"ERROR"},
                result.errors[0].message if result.errors else "Part rebuild failed",
            )
            return {"CANCELLED"}
        ui.sketch_dirty = False
        ui.sketch_applied_signature = sketch_signature(sketch)
        self.report({"INFO"}, f"Added {dimension.dimension_type.replace('_', ' ').title()} dimension.")
        tag_redraw()
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_apply_dimension(bpy.types.Operator):
    bl_idname = "parametric_cad.apply_dimension"
    bl_label = "Apply Dimension"
    bl_description = "Apply the selected driving dimension and rebuild the Part Studio"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ui = context.scene.parametric_cad_ui
        document, part, sketch = _active_sketch(context)
        if sketch is None or part is None:
            self.report({"ERROR"}, "The active Sketch is unavailable.")
            return {"CANCELLED"}
        dimension = next(
            (item for item in sketch.dimensions if item.id == ui.active_sketch_dimension_id),
            None,
        )
        if dimension is None:
            self.report({"ERROR"}, "Select a Sketch dimension first.")
            return {"CANCELLED"}
        old_entities = deepcopy(sketch.entities)
        old_value = dimension.value
        old_status, old_error = dimension.status, dimension.error_message
        try:
            dimension.value = ui.sketch_dimension_value_mm / 1000.0
            validate_dimension_conflicts(sketch, dimension)
            solved = SketchSolver().solve(sketch)
            if not solved.success:
                raise DimensionError(solved.message)
        except DimensionError as exc:
            sketch.entities = old_entities
            dimension.value = old_value
            dimension.status, dimension.error_message = old_status, old_error
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        save_document_to_scene(context.scene, document)
        result = rebuild_part(context.scene, part.id)
        if not result.success:
            sketch.entities = old_entities
            dimension.value = old_value
            dimension.status, dimension.error_message = old_status, old_error
            save_document_to_scene(context.scene, document)
            rebuild_part(context.scene, part.id)
            ui.sketch_dirty = True
            self.report(
                {"ERROR"},
                result.errors[0].message if result.errors else "Part rebuild failed",
            )
            tag_redraw()
            return {"CANCELLED"}
        ui.sketch_dirty = False
        ui.sketch_dimension_value_mm = dimension.value * 1000.0
        ui.sketch_applied_signature = sketch_signature(sketch)
        self.report({"INFO"}, "Dimension applied and Part Studio rebuilt.")
        tag_redraw()
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_delete_dimension(bpy.types.Operator):
    bl_idname = "parametric_cad.delete_dimension"
    bl_label = "Delete Dimension"
    bl_description = "Remove the selected Sketch dimension"
    bl_options = {"REGISTER", "UNDO"}

    dimension_id: bpy.props.StringProperty(options={"HIDDEN"})

    def execute(self, context):
        ui = context.scene.parametric_cad_ui
        document, part, sketch = _active_sketch(context)
        if sketch is None or part is None:
            return {"CANCELLED"}
        dimension_id = self.dimension_id or ui.active_sketch_dimension_id
        before = len(sketch.dimensions)
        sketch.dimensions = [item for item in sketch.dimensions if item.id != dimension_id]
        if len(sketch.dimensions) == before:
            self.report({"INFO"}, "Dimension is no longer present.")
            return {"CANCELLED"}
        if ui.active_sketch_dimension_id == dimension_id:
            ui.active_sketch_dimension_id = ""
        save_document_to_scene(context.scene, document)
        mark_sketch_dirty(ui, sketch)
        result = rebuild_part(context.scene, part.id)
        if not result.success:
            self.report(
                {"ERROR"},
                result.errors[0].message if result.errors else "Part rebuild failed",
            )
            return {"CANCELLED"}
        ui.sketch_dirty = False
        ui.sketch_applied_signature = sketch_signature(sketch)
        tag_redraw()
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_select_dimension(bpy.types.Operator):
    bl_idname = "parametric_cad.select_dimension"
    bl_label = "Select Dimension"
    bl_description = "Select this Sketch dimension for editing"
    bl_options = {"REGISTER"}

    dimension_id: bpy.props.StringProperty(options={"HIDDEN"})

    def execute(self, context):
        ui = context.scene.parametric_cad_ui
        document, _part, sketch = _active_sketch(context)
        if sketch is None:
            return {"CANCELLED"}
        dimension = next((item for item in sketch.dimensions if item.id == self.dimension_id), None)
        if dimension is None:
            return {"CANCELLED"}
        ui.active_sketch_dimension_id = dimension.id
        ui.sketch_dimension_type = dimension.dimension_type
        try:
            ui.sketch_dimension_value_mm = dimension_value(sketch, dimension) * 1000.0
        except DimensionError:
            ui.sketch_dimension_value_mm = dimension.value * 1000.0
        tag_redraw()
        return {"FINISHED"}


CLASSES = (
    PARAMETRIC_CAD_OT_add_dimension,
    PARAMETRIC_CAD_OT_apply_dimension,
    PARAMETRIC_CAD_OT_delete_dimension,
    PARAMETRIC_CAD_OT_select_dimension,
)
