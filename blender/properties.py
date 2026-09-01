"""Transient Blender UI state; persistent CAD data lives in CadDocument JSON."""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, PointerProperty, StringProperty

_PART_STUDIO_ITEMS = []


def _part_studio_items(_self, context):
    global _PART_STUDIO_ITEMS
    if context is not None:
        try:
            from .adapter import load_document_from_scene

            document = load_document_from_scene(context.scene)
            if document.parts:
                _PART_STUDIO_ITEMS = [
                    (part.id, part.name, f"Activate {part.name}")
                    for part in document.parts
                ]
                return _PART_STUDIO_ITEMS
        except (AttributeError, TypeError, ValueError):
            pass
    _PART_STUDIO_ITEMS = [
        ("NONE", "No Part Studios", "Create a Part Studio to begin")
    ]
    return _PART_STUDIO_ITEMS


def _active_part_changed(self, context):
    if context is None or self.active_part_id == "NONE":
        return
    from .adapter import load_document_from_scene, save_document_to_scene

    document = load_document_from_scene(context.scene)
    if document.get_part(self.active_part_id) is None:
        return
    if document.active_part_id != self.active_part_id:
        document.set_active_part(self.active_part_id)
        save_document_to_scene(context.scene, document)
    self.mode = "IDLE"
    self.active_feature_id = ""
    self.active_sketch_id = ""
    self.active_sketch_entity_id = ""
    self.selected_face_reference = ""


def _sketch_plane_items(_self, context):
    items = [
        ("DATUM|XY", "XY Plane", "Sketch on the XY datum plane"),
        ("DATUM|XZ", "XZ Plane", "Sketch on the XZ datum plane"),
        ("DATUM|YZ", "YZ Plane", "Sketch on the YZ datum plane"),
    ]
    if context is None:
        return items
    try:
        from ..features.extrude import ExtrudeFeature
        from .adapter import load_document_from_scene

        part = load_document_from_scene(context.scene).active_part
        if part:
            items.extend(
                (
                    f"FEATURE|{feature.id}|END_PLANE",
                    f"{feature.name} End Plane",
                    "Semantic plane that follows the extrusion distance",
                )
                for feature in part.features
                if isinstance(feature, ExtrudeFeature)
                and feature.operation == "NEW"
                and feature.status == "OK"
            )
    except (AttributeError, TypeError, ValueError):
        pass
    return items


def _revolve_axis_line_items(_self, context):
    if context is not None:
        try:
            from ..sketch.entities import SketchLine
            from ..sketch.sketch import SketchFeature
            from ..features.revolve import RevolveFeature
            from .adapter import load_document_from_scene

            ui = context.scene.parametric_cad_ui
            part = load_document_from_scene(context.scene).active_part
            feature = part.get_feature(ui.active_feature_id) if part else None
            if isinstance(feature, RevolveFeature):
                feature = part.get_feature(feature.sketch_id)
            if isinstance(feature, SketchFeature):
                items = [
                    (
                        entity.id,
                        f"Line {index + 1}",
                        "Use this SketchLine as the Revolve axis",
                    )
                    for index, entity in enumerate(feature.entities)
                    if isinstance(entity, SketchLine)
                ]
                if items:
                    return items
        except (AttributeError, TypeError, ValueError):
            pass
    return [("NONE", "No SketchLines", "Create a SketchLine axis first")]


class PARAMETRIC_CAD_PG_ui_state(bpy.types.PropertyGroup):
    active_part_id: EnumProperty(
        name="Active Part Studio",
        items=_part_studio_items,
        update=_active_part_changed,
    )
    mode: EnumProperty(
        name="CAD Mode",
        items=[
            ("IDLE", "Idle", "Normal CAD interaction"),
            ("SKETCH_EDIT", "Sketch Edit", "Editing a CAD sketch"),
            ("FEATURE_EDIT", "Feature Edit", "Editing a CAD feature"),
        ],
        default="IDLE",
    )
    active_feature_id: StringProperty(default="")
    active_sketch_id: StringProperty(default="")
    active_sketch_entity_id: StringProperty(default="")
    selected_face_reference: StringProperty(default="")
    show_sketches: BoolProperty(
        name="Show Sketches",
        description="Show resolved Sketch geometry outside Sketch Edit",
        default=True,
    )
    new_sketch_plane: EnumProperty(
        name="Plane",
        items=[
            ("XY", "XY Plane", "Sketch on the XY datum plane"),
            ("XZ", "XZ Plane", "Sketch on the XZ datum plane"),
            ("YZ", "YZ Plane", "Sketch on the YZ datum plane"),
        ],
        default="XY",
    )
    new_sketch_reference: EnumProperty(
        name="Sketch Plane",
        items=_sketch_plane_items,
    )
    extrude_distance_mm: FloatProperty(
        name="Distance",
        description="Extrusion distance in millimeters",
        default=20.0,
        min=0.001,
        soft_max=1000.0,
    )
    extrude_operation: EnumProperty(
        name="Operation",
        items=[
            ("NEW", "New", "Create the Part Studio body"),
            ("ADD", "Add", "Union the extrusion with the current body"),
            ("REMOVE", "Remove", "Subtract the extrusion from the current body"),
        ],
        default="NEW",
    )
    extrude_depth_mode: EnumProperty(
        name="Depth",
        items=[
            ("BLIND", "Blind", "Use the entered distance"),
            ("THROUGH_ALL", "Through All", "Span the current body bounds"),
        ],
        default="BLIND",
    )
    revolve_operation: EnumProperty(
        name="Operation",
        items=[
            ("NEW", "New", "Create the revolved Part Studio body"),
            ("ADD", "Add", "Union the revolve with the current body"),
            ("REMOVE", "Remove", "Subtract the revolve from the current body"),
        ],
        default="NEW",
    )
    revolve_axis_type: EnumProperty(
        name="Axis Type",
        items=[
            ("DATUM_AXIS", "Datum Axis", "Use the global X, Y, or Z axis"),
            ("SKETCH_LINE", "Sketch Line", "Use a persistent SketchLine axis"),
        ],
        default="DATUM_AXIS",
    )
    revolve_axis: EnumProperty(
        name="Axis",
        items=[
            ("X", "X Axis", "Global X axis"),
            ("Y", "Y Axis", "Global Y axis"),
            ("Z", "Z Axis", "Global Z axis"),
        ],
        default="Z",
    )
    revolve_axis_line_id: EnumProperty(
        name="Sketch Line",
        items=_revolve_axis_line_items,
    )
    revolve_angle_deg: FloatProperty(
        name="Angle",
        description="Revolve angle in degrees",
        default=360.0,
        min=0.001,
        max=360.0,
        soft_max=360.0,
    )
    rectangle_x_mm: FloatProperty(name="X", default=-40.0)
    rectangle_y_mm: FloatProperty(name="Y", default=-25.0)
    rectangle_width_mm: FloatProperty(name="Width", default=80.0, min=0.001)
    rectangle_height_mm: FloatProperty(name="Height", default=50.0, min=0.001)
    circle_x_mm: FloatProperty(name="Center X", default=0.0)
    circle_y_mm: FloatProperty(name="Center Y", default=0.0)
    circle_diameter_mm: FloatProperty(name="Diameter", default=10.0, min=0.001)
    mouse_x_mm: FloatProperty(name="X", default=0.0)
    mouse_y_mm: FloatProperty(name="Y", default=0.0)
    sketch_session_new: BoolProperty(default=False)
    sketch_session_backup: StringProperty(default="")


CLASSES = (PARAMETRIC_CAD_PG_ui_state,)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.parametric_cad_document = StringProperty(
        name="Parametric CAD Document",
        default="",
        options={"HIDDEN"},
    )
    bpy.types.Scene.parametric_cad_ui = PointerProperty(type=PARAMETRIC_CAD_PG_ui_state)


def unregister() -> None:
    del bpy.types.Scene.parametric_cad_ui
    del bpy.types.Scene.parametric_cad_document
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
