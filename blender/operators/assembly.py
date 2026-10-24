"""Assembly organization, numeric placements, and native two-window navigation."""

from math import degrees, radians

import bpy
from mathutils import Matrix

from ...core.assembly import Assembly, AssemblyInstance
from ...core.transform import Transform
from ..adapter import load_document, save_document, rebuild_part
from ..environments import (
    ASSEMBLY, PART_STUDIO, commit_assembly, open_environment, part_studio_scene,
    instance_object, remove_assembly_geometry, show_active_part, sync_assembly,
)
from ..properties import _part_studio_items


def selected_instance(scene, document=None):
    """Resolve Assembly UI selection without consulting active Part Studio state."""
    document = document or load_document()
    ui = scene.parametric_cad_ui
    return document.get_instance(ui.active_assembly_id, ui.selected_instance_id)


class _AssemblyOperator:
    @classmethod
    def poll(cls, context):
        return context.scene.get("cad_scene_role") == ASSEMBLY


class PARAMETRIC_CAD_OT_new_assembly(_AssemblyOperator, bpy.types.Operator):
    bl_idname = "parametric_cad.new_assembly"
    bl_label = "New Assembly"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        document = load_document()
        assembly = document.add_assembly(Assembly(name=f"Assembly {len(document.assemblies) + 1}"))
        commit_assembly(document, assembly, context.scene)
        context.scene.parametric_cad_ui.active_assembly_id = assembly.id
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_rename_assembly(_AssemblyOperator, bpy.types.Operator):
    bl_idname = "parametric_cad.rename_assembly"
    bl_label = "Rename Assembly"
    bl_options = {"REGISTER", "UNDO"}
    name: bpy.props.StringProperty(name="Name")

    def invoke(self, context, _event):
        assembly = load_document().get_assembly(context.scene.parametric_cad_ui.active_assembly_id)
        if assembly is None:
            return {"CANCELLED"}
        self.name = assembly.name
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        document = load_document()
        assembly = document.get_assembly(context.scene.parametric_cad_ui.active_assembly_id)
        if assembly is None or not self.name.strip():
            return {"CANCELLED"}
        assembly.name = self.name.strip()
        save_document(document)
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_delete_assembly(_AssemblyOperator, bpy.types.Operator):
    bl_idname = "parametric_cad.delete_assembly"
    bl_label = "Delete Assembly"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        document = load_document()
        ui = context.scene.parametric_cad_ui
        removed = document.remove_assembly(ui.active_assembly_id)
        if removed is None:
            return {"CANCELLED"}
        save_document(document)
        remove_assembly_geometry(removed.id)
        ui.active_assembly_id = document.assemblies[0].id if document.assemblies else "NONE"
        ui.selected_instance_id = ""
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_add_assembly_instance(_AssemblyOperator, bpy.types.Operator):
    bl_idname = "parametric_cad.add_assembly_instance"
    bl_label = "Add Part"
    bl_options = {"REGISTER", "UNDO"}
    part_id: bpy.props.EnumProperty(name="Part Studio", items=_part_studio_items)
    name: bpy.props.StringProperty(name="Instance Name")

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        document = load_document()
        part = document.get_part(self.part_id)
        ui = context.scene.parametric_cad_ui
        if part is None or document.get_assembly(ui.active_assembly_id) is None:
            return {"CANCELLED"}
        # Ensure the original source exists; an instance never owns a mesh copy.
        rebuild_part(part_studio_scene(), part.id)
        document = load_document()
        instance = document.add_instance(ui.active_assembly_id, AssemblyInstance(
            name=self.name.strip() or part.name, part_studio_id=part.id,
        ))
        commit_assembly(document, document.get_assembly(ui.active_assembly_id), context.scene)
        ui.selected_instance_id = instance.id
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_select_assembly_instance(_AssemblyOperator, bpy.types.Operator):
    bl_idname = "parametric_cad.select_assembly_instance"
    bl_label = "Select Instance"
    instance_id: bpy.props.StringProperty()

    def execute(self, context):
        context.scene.parametric_cad_ui.selected_instance_id = self.instance_id
        obj = instance_object(self.instance_id)
        if obj is not None and obj.name in context.view_layer.objects:
            for selected in context.selected_objects:
                selected.select_set(False)
            obj.select_set(True)
            context.view_layer.objects.active = obj
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_transform_assembly_instance(_AssemblyOperator, bpy.types.Operator):
    bl_idname = "parametric_cad.transform_assembly_instance"
    bl_label = "Transform Instance"
    bl_options = {"REGISTER", "UNDO"}
    translation_mm: bpy.props.FloatVectorProperty(name="Translation (mm)", size=3)
    rotation_deg: bpy.props.FloatVectorProperty(name="Rotation (degrees)", size=3)
    name: bpy.props.StringProperty(name="Name")
    suppressed: bpy.props.BoolProperty(name="Suppressed")

    def invoke(self, context, _event):
        instance = selected_instance(context.scene)
        if instance is None:
            return {"CANCELLED"}
        matrix = Matrix(instance.transform)
        self.translation_mm = tuple(value * 1000.0 for value in matrix.translation)
        self.rotation_deg = tuple(degrees(value) for value in matrix.to_euler('XYZ'))
        self.name = instance.name
        self.suppressed = instance.suppressed
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        document = load_document()
        instance = selected_instance(context.scene, document)
        if instance is None:
            return {"CANCELLED"}
        instance.transform = Transform(
            translation=tuple(value / 1000.0 for value in self.translation_mm),
            rotation=tuple(radians(value) for value in self.rotation_deg),
        ).matrix
        instance.name = self.name.strip() or instance.name
        instance.suppressed = self.suppressed
        commit_assembly(document, document.get_assembly(context.scene.parametric_cad_ui.active_assembly_id), context.scene)
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_remove_assembly_instance(_AssemblyOperator, bpy.types.Operator):
    bl_idname = "parametric_cad.remove_assembly_instance"
    bl_label = "Remove Instance"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        document = load_document()
        ui = context.scene.parametric_cad_ui
        document.remove_instance(ui.active_assembly_id, ui.selected_instance_id)
        commit_assembly(document, document.get_assembly(ui.active_assembly_id), context.scene)
        ui.selected_instance_id = ""
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_edit_source_part(_AssemblyOperator, bpy.types.Operator):
    bl_idname = "parametric_cad.edit_source_part"
    bl_label = "Edit Source Part"

    def execute(self, context):
        document = load_document()
        instance = selected_instance(context.scene, document)
        if instance is None:
            return {"CANCELLED"}
        scene = part_studio_scene()
        document.set_active_part(instance.part_studio_id)
        save_document(document)
        if scene.parametric_cad_ui.active_part_id != instance.part_studio_id:
            scene.parametric_cad_ui.active_part_id = instance.part_studio_id
        show_active_part(scene, instance.part_studio_id)
        open_environment(context, PART_STUDIO, new_window=False)
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_open_assembly_window(bpy.types.Operator):
    bl_idname = "parametric_cad.open_assembly_window"
    bl_label = "Open Assembly Window"

    def execute(self, context):
        part_studio_scene()
        open_environment(context, ASSEMBLY)
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_open_part_studio_window(bpy.types.Operator):
    bl_idname = "parametric_cad.open_part_studio_window"
    bl_label = "Open Part Studio Window"

    def execute(self, context):
        open_environment(context, PART_STUDIO)
        return {"FINISHED"}


def draw_assembly(layout, context, document):
    """Present the Assembly context without source Sketch or feature editors."""
    ui = context.scene.parametric_cad_ui
    layout.label(text="ASSEMBLY", icon="OUTLINER_COLLECTION")
    row = layout.row(align=True)
    row.prop(ui, "active_assembly_id", text="")
    row.operator("parametric_cad.new_assembly", text="", icon="ADD")
    layout.operator("parametric_cad.open_part_studio_window")
    assembly = document.get_assembly(ui.active_assembly_id)
    if assembly is None:
        return
    row = layout.row(align=True)
    row.operator("parametric_cad.rename_assembly", text="Rename")
    row.operator("parametric_cad.delete_assembly", text="Delete")
    layout.label(text="INSTANCES")
    for instance in assembly.instances:
        row = layout.row(align=True)
        op = row.operator("parametric_cad.select_assembly_instance", text=instance.name,
                          depress=ui.selected_instance_id == instance.id,
                          icon="HIDE_ON" if instance.suppressed else "OUTLINER_OB_EMPTY")
        op.instance_id = instance.id
        obj = instance_object(instance.id)
        if obj is not None and obj.get("cad_diagnostic"):
            warning = layout.column(align=True)
            warning.alert = True
            if obj.get("cad_stale"):
                warning.label(text="Source Part rebuild failed.", icon="ERROR")
                warning.label(text="Displaying last valid geometry.")
            else:
                warning.label(text=obj["cad_diagnostic"], icon="ERROR")
    layout.operator("parametric_cad.add_assembly_instance")
    actions = layout.column(align=True)
    actions.enabled = selected_instance(context.scene, document) is not None
    actions.operator("parametric_cad.edit_source_part")
    actions.operator("parametric_cad.transform_assembly_instance", text="Transform")
    actions.operator("parametric_cad.remove_assembly_instance")


CLASSES = (
    PARAMETRIC_CAD_OT_new_assembly, PARAMETRIC_CAD_OT_rename_assembly,
    PARAMETRIC_CAD_OT_delete_assembly, PARAMETRIC_CAD_OT_add_assembly_instance,
    PARAMETRIC_CAD_OT_select_assembly_instance, PARAMETRIC_CAD_OT_transform_assembly_instance,
    PARAMETRIC_CAD_OT_remove_assembly_instance, PARAMETRIC_CAD_OT_edit_source_part,
    PARAMETRIC_CAD_OT_open_assembly_window, PARAMETRIC_CAD_OT_open_part_studio_window,
)
