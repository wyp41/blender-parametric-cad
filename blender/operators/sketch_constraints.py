"""Small Blender UI actions for listing and removing Sketch constraints."""

from __future__ import annotations

from copy import deepcopy

import bpy

from ...blender.adapter import load_document_from_scene, rebuild_part, save_document_to_scene
from ...sketch.sketch import SketchFeature
from ...sketch.solver import SketchSolver
from .sketch import sketch_signature


def _active_sketch(context):
    ui = context.scene.parametric_cad_ui
    document = load_document_from_scene(context.scene)
    part = document.active_part
    sketch = part.get_feature(ui.active_sketch_id) if part else None
    return document, part, sketch if isinstance(sketch, SketchFeature) else None


class PARAMETRIC_CAD_OT_delete_constraint(bpy.types.Operator):
    bl_idname = "parametric_cad.delete_constraint"
    bl_label = "Delete Constraint"
    bl_description = "Delete a Sketch constraint and rebuild"
    bl_options = {"REGISTER", "UNDO"}

    constraint_id: bpy.props.StringProperty(options={"HIDDEN"})

    def execute(self, context):
        ui = context.scene.parametric_cad_ui
        document, part, sketch = _active_sketch(context)
        if sketch is None or part is None:
            return {"CANCELLED"}
        index = next(
            (index for index, item in enumerate(sketch.constraints) if item.id == self.constraint_id),
            None,
        )
        if index is None:
            return {"CANCELLED"}
        old_constraints = deepcopy(sketch.constraints)
        sketch.constraints.pop(index)
        solved = SketchSolver().solve(sketch)
        if not solved.success:
            sketch.constraints = old_constraints
            self.report({"ERROR"}, solved.message)
            return {"CANCELLED"}
        save_document_to_scene(context.scene, document)
        result = rebuild_part(context.scene, part.id)
        if not result.success:
            sketch.constraints = old_constraints
            save_document_to_scene(context.scene, document)
            self.report({"ERROR"}, result.errors[0].message if result.errors else "Rebuild failed")
            return {"CANCELLED"}
        ui.sketch_applied_signature = sketch_signature(sketch)
        ui.sketch_dirty = False
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_toggle_constraint(bpy.types.Operator):
    bl_idname = "parametric_cad.toggle_constraint"
    bl_label = "Enable Constraint"
    bl_description = "Enable or disable a Sketch constraint"
    bl_options = {"REGISTER", "UNDO"}

    constraint_id: bpy.props.StringProperty(options={"HIDDEN"})
    enabled: bpy.props.BoolProperty(default=True, options={"HIDDEN"})

    def execute(self, context):
        ui = context.scene.parametric_cad_ui
        document, part, sketch = _active_sketch(context)
        if sketch is None or part is None:
            return {"CANCELLED"}
        constraint = next((item for item in sketch.constraints if item.id == self.constraint_id), None)
        if constraint is None:
            return {"CANCELLED"}
        old_constraints = deepcopy(sketch.constraints)
        constraint.enabled = self.enabled
        solved = SketchSolver().solve(sketch)
        if not solved.success:
            sketch.constraints = old_constraints
            self.report({"ERROR"}, solved.message)
            return {"CANCELLED"}
        save_document_to_scene(context.scene, document)
        result = rebuild_part(context.scene, part.id)
        if not result.success:
            sketch.constraints = old_constraints
            save_document_to_scene(context.scene, document)
            self.report({"ERROR"}, result.errors[0].message if result.errors else "Rebuild failed")
            return {"CANCELLED"}
        ui.sketch_applied_signature = sketch_signature(sketch)
        ui.sketch_dirty = False
        return {"FINISHED"}


CLASSES = (
    PARAMETRIC_CAD_OT_delete_constraint,
    PARAMETRIC_CAD_OT_toggle_constraint,
)
