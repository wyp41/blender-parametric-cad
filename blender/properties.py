"""Transient Blender UI state; persistent CAD data lives in CadDocument JSON."""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, PointerProperty, StringProperty

_PART_STUDIO_ITEMS = []
_MIRROR_SOURCE_ITEMS = []
_SKETCH_PLANE_ITEMS = []
_REVOLVE_AXIS_ITEMS = []


def _part_studio_items(_self, context):
    global _PART_STUDIO_ITEMS
    if context is not None:
        try:
            from .adapter import load_document_from_scene

            document = load_document_from_scene(context.scene)
            if document.parts:
                name_counts = {}
                for part in document.parts:
                    name_counts[part.name] = name_counts.get(part.name, 0) + 1
                _PART_STUDIO_ITEMS = [
                    (
                        part.id,
                        (
                            f"{part.name} P{index + 1:02d}"
                            if name_counts[part.name] > 1
                            else part.name
                        ),
                        f"Activate {part.name} ({part.id[:8]})",
                    )
                    for index, part in enumerate(document.parts)
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

    try:
        document = load_document_from_scene(context.scene)
    except (AttributeError, TypeError, ValueError):
        return
    if document.get_part(self.active_part_id) is None:
        return
    if document.active_part_id != self.active_part_id:
        document.set_active_part(self.active_part_id)
        save_document_to_scene(context.scene, document)
    self.mode = "IDLE"
    self.active_feature_id = ""
    self.active_sketch_id = ""
    self.active_sketch_entity_id = ""
    self.active_sketch_entity_ids = "[]"
    self.selected_face_reference = ""


def _sketch_plane_items(_self, context):
    global _SKETCH_PLANE_ITEMS
    items = [
        ("DATUM|XY", "XY Plane", "Sketch on the XY datum plane"),
        ("DATUM|XZ", "XZ Plane", "Sketch on the XZ datum plane"),
        ("DATUM|YZ", "YZ Plane", "Sketch on the YZ datum plane"),
    ]
    if context is None:
        _SKETCH_PLANE_ITEMS = items
        return _SKETCH_PLANE_ITEMS
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
    # Blender keeps references to strings returned by dynamic EnumProperty
    # callbacks. Retain the list at module scope so those strings remain valid.
    _SKETCH_PLANE_ITEMS = items
    return _SKETCH_PLANE_ITEMS


def _revolve_axis_line_items(_self, context):
    global _REVOLVE_AXIS_ITEMS
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
                    _REVOLVE_AXIS_ITEMS = items
                    return _REVOLVE_AXIS_ITEMS
        except (AttributeError, TypeError, ValueError):
            pass
    _REVOLVE_AXIS_ITEMS = [
        ("NONE", "No SketchLines", "Create a SketchLine axis first")
    ]
    return _REVOLVE_AXIS_ITEMS


def _mirror_source_items(_self, context):
    """List earlier additive Extrude/Revolve features that can be mirrored."""

    global _MIRROR_SOURCE_ITEMS
    if context is not None:
        try:
            from ..features.extrude import ExtrudeFeature
            from ..features.revolve import RevolveFeature
            from .adapter import load_document_from_scene

            part = load_document_from_scene(context.scene).active_part
            if part is not None:
                ui = getattr(context.scene, "parametric_cad_ui", None)
                active_index = part.get_feature_index(ui.active_feature_id) if ui else None
                if active_index is not None and part.features[active_index].feature_type == "MIRROR":
                    source_features = part.features[:active_index]
                else:
                    source_features = part.features
                _MIRROR_SOURCE_ITEMS = [
                    (
                        feature.id,
                        feature.name,
                        "Mirror this additive Extrude or Revolve feature",
                    )
                    for feature in source_features
                    if isinstance(feature, (ExtrudeFeature, RevolveFeature))
                    and feature.operation == "ADD"
                    and not feature.suppressed
                ]
                if _MIRROR_SOURCE_ITEMS:
                    return _MIRROR_SOURCE_ITEMS
        except (AttributeError, TypeError, ValueError):
            pass
    _MIRROR_SOURCE_ITEMS = [
        (
            "NONE",
            "No additive features",
            "Create an additive Extrude or Revolve first",
        )
    ]
    return _MIRROR_SOURCE_ITEMS


def _mirror_plane_items(_self, context):
    """Return datum and supported semantic planes for Mirror."""

    return _sketch_plane_items(_self, context)


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
    active_sketch_entity_ids: StringProperty(
        name="Selected Sketch Geometry",
        description="JSON list of selected sketch entity IDs for group edits",
        default="[]",
        options={"HIDDEN"},
    )
    sketch_dirty: BoolProperty(
        name="Sketch Has Unapplied Changes",
        description="Sketch source changed but its result has not been rebuilt",
        default=False,
    )
    selected_face_reference: StringProperty(default="")
    show_sketches: BoolProperty(
        name="Show Sketches",
        description="Show resolved Sketch geometry outside Sketch Edit",
        default=True,
    )
    export_format: EnumProperty(
        name="Export Format",
        items=[
            ("STL", "STL", "Export a mesh for fabrication"),
            ("OBJ", "OBJ", "Export an OBJ mesh"),
            ("PLY", "PLY", "Export a polygon mesh"),
        ],
        default="STL",
    )
    export_filepath: StringProperty(
        name="Export Path",
        description="File path for exporting the active Part Studio",
        subtype="FILE_PATH",
        default="",
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
    new_sketch_offset_mm: FloatProperty(
        name="Plane Offset",
        description="Offset the new Sketch along its resolved support normal",
        default=0.0,
    )
    sketch_plane_offset_mm: FloatProperty(
        name="Plane Offset",
        description="Offset the active Sketch along its resolved support normal",
        default=0.0,
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
    revolve_axis_reverse: BoolProperty(
        name="Reverse Axis Direction",
        description="Reverse the sweep direction; this is visible only for partial Revolves",
        default=False,
    )
    revolve_angle_deg: FloatProperty(
        name="Angle",
        description="Revolve angle in degrees",
        default=360.0,
        min=0.001,
        max=360.0,
        soft_max=360.0,
    )
    transform_translate_x_mm: FloatProperty(name="Translate X", default=0.0)
    transform_translate_y_mm: FloatProperty(name="Translate Y", default=0.0)
    transform_translate_z_mm: FloatProperty(name="Translate Z", default=0.0)
    transform_rotate_x_deg: FloatProperty(name="Rotate X", default=0.0)
    transform_rotate_y_deg: FloatProperty(name="Rotate Y", default=0.0)
    transform_rotate_z_deg: FloatProperty(name="Rotate Z", default=0.0)
    mirror_source_feature_id: EnumProperty(
        name="Source Feature",
        items=_mirror_source_items,
    )
    mirror_plane_reference: EnumProperty(
        name="Mirror Plane",
        items=_mirror_plane_items,
    )
    mirror_plane_offset_mm: FloatProperty(
        name="Plane Offset",
        description="Offset the mirror plane along its normal",
        default=0.0,
    )
    rectangle_x_mm: FloatProperty(name="X", default=-40.0)
    rectangle_y_mm: FloatProperty(name="Y", default=-25.0)
    rectangle_width_mm: FloatProperty(name="Width", default=80.0, min=0.001)
    rectangle_height_mm: FloatProperty(name="Height", default=50.0, min=0.001)
    circle_x_mm: FloatProperty(name="Center X", default=0.0)
    circle_y_mm: FloatProperty(name="Center Y", default=0.0)
    circle_diameter_mm: FloatProperty(name="Diameter", default=10.0, min=0.001)
    arc_x_mm: FloatProperty(name="Center X", default=0.0)
    arc_y_mm: FloatProperty(name="Center Y", default=0.0)
    arc_radius_mm: FloatProperty(name="Radius", default=10.0, min=0.001)
    arc_start_deg: FloatProperty(name="Start Angle", default=0.0)
    arc_end_deg: FloatProperty(name="End Angle", default=90.0)
    mouse_x_mm: FloatProperty(name="X", default=0.0)
    mouse_y_mm: FloatProperty(name="Y", default=0.0)
    sketch_session_new: BoolProperty(default=False)
    sketch_session_backup: StringProperty(default="")


CLASSES = (PARAMETRIC_CAD_PG_ui_state,)


def _registered_class(cls):
    """Return the class currently registered under this Blender type name."""

    try:
        return getattr(bpy.types, cls.__name__, None)
    except (AttributeError, RuntimeError):
        return None


def register() -> None:
    for cls in CLASSES:
        if _registered_class(cls) is None:
            bpy.utils.register_class(cls)
    if not hasattr(bpy.types.Scene, "parametric_cad_document"):
        bpy.types.Scene.parametric_cad_document = StringProperty(
            name="Parametric CAD Document",
            default="",
            options={"HIDDEN"},
        )
    if not hasattr(bpy.types.Scene, "parametric_cad_ui"):
        bpy.types.Scene.parametric_cad_ui = PointerProperty(
            type=PARAMETRIC_CAD_PG_ui_state
        )


def unregister() -> None:
    if hasattr(bpy.types.Scene, "parametric_cad_ui"):
        del bpy.types.Scene.parametric_cad_ui
    if hasattr(bpy.types.Scene, "parametric_cad_document"):
        del bpy.types.Scene.parametric_cad_document
    for cls in reversed(CLASSES):
        registered = _registered_class(cls)
        if registered is not None:
            bpy.utils.unregister_class(registered)
