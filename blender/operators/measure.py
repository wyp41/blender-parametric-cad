"""CAD-friendly, non-destructive viewport measurement tools."""

from __future__ import annotations

import bpy
from bpy_extras import view3d_utils
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Vector

from ...sketch.plane import PlaneResolutionError, resolve_sketch_plane_from_history
from ...sketch.sketch import SketchFeature, sketch_to_world
from ...sketch.snapping import snap_targets
from ..adapter import CadDocumentError, load_document_from_scene
from ..viewport.projection import screen_to_sketch
from ..viewport.sketch_overlay import (
    clear_measurement,
    clear_measurement_pending,
    set_measurement_pending,
    set_measurement_result,
    tag_redraw,
)


def _window_region(context):
    area = getattr(context, "area", None)
    if area is None:
        return None
    return next(
        (region for region in area.regions if region.type == "WINDOW"),
        None,
    )


def _event_coordinate(event, region) -> tuple[float, float]:
    return (event.mouse_x - region.x, event.mouse_y - region.y)


def _snap_tolerance(context) -> float:
    ui = getattr(getattr(context, "scene", None), "parametric_cad_ui", None)
    try:
        return max(3.0, min(40.0, float(ui.measure_snap_tolerance_px)))
    except (AttributeError, TypeError, ValueError):
        return 14.0


def _mesh_point(context, event):
    region = _window_region(context)
    region_3d = getattr(getattr(context, "space_data", None), "region_3d", None)
    if region is None or region_3d is None:
        return None
    coordinate = _event_coordinate(event, region)
    try:
        origin = view3d_utils.region_2d_to_origin_3d(region, region_3d, coordinate)
        direction = view3d_utils.region_2d_to_vector_3d(region, region_3d, coordinate)
        hit, location, _normal, polygon_index, obj, _matrix = context.scene.ray_cast(
            context.evaluated_depsgraph_get(), origin, direction
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None
    if not hit or obj is None:
        return None
    point = Vector(location)
    label = f"Surface · {getattr(obj, 'name', 'Object')}"
    if getattr(obj, "type", None) != "MESH":
        return tuple(point), label
    mesh = getattr(obj, "data", None)
    if mesh is None or polygon_index < 0 or polygon_index >= len(mesh.polygons):
        return tuple(point), label
    tolerance = _snap_tolerance(context)
    cursor = Vector(coordinate)
    nearest = None
    nearest_distance = tolerance
    try:
        polygon = mesh.polygons[polygon_index]
        for vertex_index in polygon.vertices:
            vertex = mesh.vertices[vertex_index]
            world = Vector(obj.matrix_world @ vertex.co)
            screen = location_3d_to_region_2d(region, region_3d, world)
            if screen is None:
                continue
            distance = (screen - cursor).length
            if distance <= nearest_distance:
                nearest = world
                nearest_distance = distance
    except (AttributeError, IndexError, ReferenceError, RuntimeError, TypeError, ValueError):
        nearest = None
    if nearest is not None:
        return tuple(nearest), f"Vertex · {getattr(obj, 'name', 'Object')}"
    return tuple(point), label


def _sketch_point(context, event):
    """Map a click to the active Sketch plane when no mesh was ray-hit."""

    scene = getattr(context, "scene", None)
    ui = getattr(scene, "parametric_cad_ui", None)
    if ui is None or ui.mode != "SKETCH_EDIT" or not ui.active_sketch_id:
        return None
    try:
        document = load_document_from_scene(scene)
        part = document.active_part
        sketch = part.get_feature(ui.active_sketch_id) if part else None
        if not isinstance(sketch, SketchFeature):
            return None
        sketch.apply_resolved_plane(
            resolve_sketch_plane_from_history(part, sketch.id)
        )
        region = _window_region(context)
        if region is None:
            return None
        with context.temp_override(region=region):
            point_2d = screen_to_sketch(context, event, sketch)
        if point_2d is None:
            return None
        world = sketch_to_world(sketch, *point_2d)
        region_3d = getattr(getattr(context, "space_data", None), "region_3d", None)
        if region_3d is None:
            return tuple(world), f"Sketch point · {sketch.name}"
        cursor = Vector(_event_coordinate(event, region))
        nearest = None
        nearest_distance = _snap_tolerance(context)
        for target in snap_targets(sketch.entities):
            candidate = sketch_to_world(sketch, *target)
            screen = location_3d_to_region_2d(region, region_3d, candidate)
            if screen is None:
                continue
            distance = (screen - cursor).length
            if distance <= nearest_distance:
                nearest = candidate
                nearest_distance = distance
        return tuple(nearest or world), (
            f"Sketch snap · {sketch.name}" if nearest is not None
            else f"Sketch point · {sketch.name}"
        )
    except (
        AttributeError,
        CadDocumentError,
        KeyError,
        PlaneResolutionError,
        ReferenceError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        return None


def _pick_point(context, event):
    return _mesh_point(context, event) or _sketch_point(context, event)


def _set_point(ui, property_name: str, point) -> None:
    setattr(ui, property_name, tuple(float(value) for value in point))


def _reset_measurement_state(ui) -> None:
    ui.measure_pending = False
    ui.measure_has_result = False
    ui.measure_point_a = (0.0, 0.0, 0.0)
    ui.measure_point_b = (0.0, 0.0, 0.0)
    ui.measure_distance_mm = 0.0
    ui.measure_delta_x_mm = 0.0
    ui.measure_delta_y_mm = 0.0
    ui.measure_delta_z_mm = 0.0
    ui.measure_point_a_label = ""
    ui.measure_point_b_label = ""


class PARAMETRIC_CAD_OT_measure(bpy.types.Operator):
    bl_idname = "parametric_cad.measure"
    bl_label = "CAD Measure"
    bl_description = "Measure true 3D distance between two snapped CAD points"
    bl_options = {"BLOCKING", "REGISTER"}

    def invoke(self, context, _event):
        if getattr(context, "area", None) is None or context.area.type != "VIEW_3D":
            self.report({"ERROR"}, "CAD Measure must run in a 3D View.")
            return {"CANCELLED"}
        self.first_point = None
        self.first_label = ""
        ui = getattr(context.scene, "parametric_cad_ui", None)
        if ui is not None:
            _reset_measurement_state(ui)
        clear_measurement()
        context.window_manager.modal_handler_add(self)
        context.area.header_text_set(
            "CAD Measure: click first point, click second point; Esc exits"
        )
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        ui = getattr(getattr(context, "scene", None), "parametric_cad_ui", None)
        if ui is None:
            return {"CANCELLED"}
        if event.type in {"ESC", "RIGHTMOUSE"}:
            ui.measure_pending = False
            clear_measurement_pending()
            context.area.header_text_set(None)
            tag_redraw()
            return {"CANCELLED"}
        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            return {"PASS_THROUGH"}
        if event.type == "MOUSEMOVE" and self.first_point is not None:
            candidate = _pick_point(context, event)
            if candidate is None:
                clear_measurement_pending()
            else:
                set_measurement_pending(self.first_point, candidate[0])
            return {"RUNNING_MODAL"}
        if event.type != "LEFTMOUSE" or event.value != "PRESS":
            return {"RUNNING_MODAL"}
        picked = _pick_point(context, event)
        if picked is None:
            self.report({"WARNING"}, "Move over a mesh surface or the active Sketch plane.")
            return {"RUNNING_MODAL"}
        point, label = picked
        if self.first_point is None:
            self.first_point = point
            self.first_label = label
            _reset_measurement_state(ui)
            clear_measurement()
            _set_point(ui, "measure_point_a", point)
            ui.measure_point_a_label = label
            ui.measure_pending = True
            set_measurement_pending(point)
            context.area.header_text_set(
                "CAD Measure: first point set; click the second point"
            )
            return {"RUNNING_MODAL"}

        delta = tuple(point[index] - self.first_point[index] for index in range(3))
        distance = Vector(delta).length
        _set_point(ui, "measure_point_a", self.first_point)
        _set_point(ui, "measure_point_b", point)
        ui.measure_point_a_label = self.first_label
        ui.measure_point_b_label = label
        ui.measure_distance_mm = distance * 1000.0
        ui.measure_delta_x_mm = delta[0] * 1000.0
        ui.measure_delta_y_mm = delta[1] * 1000.0
        ui.measure_delta_z_mm = delta[2] * 1000.0
        ui.measure_pending = False
        ui.measure_has_result = True
        set_measurement_result(
            self.first_point,
            point,
            ui.measure_distance_mm,
            (ui.measure_delta_x_mm, ui.measure_delta_y_mm, ui.measure_delta_z_mm),
            self.first_label,
            label,
        )
        self.first_point = None
        self.first_label = ""
        context.area.header_text_set(
            "CAD Measure: result saved; click first point for another measurement; Esc exits"
        )
        self.report({"INFO"}, f"Distance: {ui.measure_distance_mm:.2f} mm")
        return {"RUNNING_MODAL"}


class PARAMETRIC_CAD_OT_clear_measurement(bpy.types.Operator):
    bl_idname = "parametric_cad.clear_measurement"
    bl_label = "Clear Measurement"
    bl_description = "Remove the current CAD measurement overlay"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ui = getattr(getattr(context, "scene", None), "parametric_cad_ui", None)
        if ui is not None:
            _reset_measurement_state(ui)
        clear_measurement()
        self.report({"INFO"}, "CAD measurement cleared.")
        return {"FINISHED"}


CLASSES = (
    PARAMETRIC_CAD_OT_measure,
    PARAMETRIC_CAD_OT_clear_measurement,
)
