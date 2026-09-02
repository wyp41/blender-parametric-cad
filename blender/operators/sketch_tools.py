"""Modal sketch drawing, selection, and region editing tools."""

from __future__ import annotations

import json
from math import atan2, cos, degrees, hypot, pi, sin
from types import SimpleNamespace

import bpy

from ...sketch.entities import SketchArc, SketchCircle, SketchLine
from ...sketch.numeric import arc_parameters, circle_parameters, rectangle_parameters
from ...sketch.plane import PlaneResolutionError, resolve_sketch_plane_from_history
from ...sketch.profile import ProfileDetector
from ...sketch.snapping import snap_point
from ...sketch.sketch import SketchFeature, sketch_to_world
from ..adapter import load_document_from_scene, save_document_to_scene
from ..viewport.projection import screen_to_sketch
from ..viewport.sketch_overlay import (
    clear_preview,
    clear_snap_preview,
    set_preview,
    set_snap_preview,
    tag_redraw,
)


class _ModalSketchTool:
    first_point: tuple[float, float] | None = None
    snap_points = False

    def invoke(self, context, _event):
        ui = context.scene.parametric_cad_ui
        if context.area.type != "VIEW_3D" or ui.mode != "SKETCH_EDIT":
            self.report({"ERROR"}, "Enter Sketch Edit in a 3D View first")
            return {"CANCELLED"}
        document = load_document_from_scene(context.scene)
        part = document.active_part
        if not isinstance(part.get_feature(ui.active_sketch_id) if part else None, SketchFeature):
            self.report({"ERROR"}, "The active sketch is unavailable")
            return {"CANCELLED"}
        self.first_point = None
        clear_preview()
        context.window_manager.modal_handler_add(self)
        context.area.header_text_set("CAD: click first point; Esc cancels tool")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"}:
            self._finish(context)
            return {"CANCELLED"}
        if event.type == "MOUSEMOVE":
            point, sketch = self._point_and_sketch(context, event)
            if point is not None:
                ui = context.scene.parametric_cad_ui
                ui.mouse_x_mm, ui.mouse_y_mm = point[0] * 1000.0, point[1] * 1000.0
            if self.first_point is not None and point is not None and sketch is not None:
                self._update_preview(sketch, self.first_point, point)
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            point, sketch = self._point_and_sketch(context, event)
            if point is None or sketch is None:
                return {"RUNNING_MODAL"}
            if self.first_point is None:
                self.first_point = point
                context.area.header_text_set("CAD: click second point; Esc cancels tool")
                return {"RUNNING_MODAL"}
            document = load_document_from_scene(context.scene)
            part = document.active_part
            stored = part.get_feature(sketch.id) if part else None
            if isinstance(stored, SketchFeature):
                self._commit(stored, self.first_point, point)
                ui = context.scene.parametric_cad_ui
                ui.active_sketch_entity_id = ""
                ui.active_sketch_entity_ids = "[]"
                ui.sketch_dirty = True
                save_document_to_scene(context.scene, document)
            self._finish(context)
            return {"FINISHED"}
        return {"RUNNING_MODAL"}

    def _point_and_sketch(self, context, event):
        document = load_document_from_scene(context.scene)
        part = document.active_part
        sketch = part.get_feature(context.scene.parametric_cad_ui.active_sketch_id) if part else None
        if not isinstance(sketch, SketchFeature):
            return None, None
        try:
            sketch.apply_resolved_plane(resolve_sketch_plane_from_history(part, sketch.id))
        except PlaneResolutionError:
            clear_snap_preview()
            return None, None
        point = screen_to_sketch(context, event, sketch)
        if point is None:
            clear_snap_preview()
            return None, sketch
        if self.snap_points:
            raw_point = point
            point = _snap_point(sketch, point)
            set_snap_preview(
                sketch_to_world(sketch, *point),
                (sketch.x_axis, sketch.y_axis),
                snapped=point != raw_point,
            )
        else:
            clear_snap_preview()
        return point, sketch

    def _update_preview(self, sketch, first, second):
        raise NotImplementedError

    def _commit(self, sketch, first, second):
        raise NotImplementedError

    @staticmethod
    def _finish(context) -> None:
        clear_preview()
        context.area.header_text_set(None)
        tag_redraw()


class PARAMETRIC_CAD_OT_draw_line(_ModalSketchTool, bpy.types.Operator):
    bl_idname = "parametric_cad.draw_line"
    bl_label = "Line"
    bl_options = {"REGISTER", "UNDO", "BLOCKING"}
    snap_points = True

    def _update_preview(self, sketch, first, second):
        set_preview([sketch_to_world(sketch, *first), sketch_to_world(sketch, *second)])

    def _commit(self, sketch, first, second):
        if first != second:
            _split_line_at_point(sketch, first)
            _split_line_at_point(sketch, second)
            sketch.entities.append(
                SketchLine(x1=first[0], y1=first[1], x2=second[0], y2=second[1])
            )


class PARAMETRIC_CAD_OT_draw_rectangle(_ModalSketchTool, bpy.types.Operator):
    bl_idname = "parametric_cad.draw_rectangle"
    bl_label = "Rectangle"
    bl_options = {"REGISTER", "UNDO", "BLOCKING"}
    snap_points = True

    @staticmethod
    def _corners(first, second):
        return [first, (second[0], first[1]), second, (first[0], second[1])]

    def _update_preview(self, sketch, first, second):
        set_preview(
            [sketch_to_world(sketch, *point) for point in self._corners(first, second)],
            closed=True,
        )

    def _commit(self, sketch, first, second):
        if first[0] == second[0] or first[1] == second[1]:
            return
        corners = self._corners(first, second)
        for index in range(4):
            start, end = corners[index], corners[(index + 1) % 4]
            sketch.entities.append(
                SketchLine(x1=start[0], y1=start[1], x2=end[0], y2=end[1])
            )


class PARAMETRIC_CAD_OT_draw_circle(_ModalSketchTool, bpy.types.Operator):
    bl_idname = "parametric_cad.draw_circle"
    bl_label = "Circle"
    bl_options = {"REGISTER", "UNDO", "BLOCKING"}
    snap_points = True

    def _update_preview(self, sketch, first, second):
        radius = hypot(second[0] - first[0], second[1] - first[1])
        points = [
            sketch_to_world(
                sketch,
                first[0] + radius * cos(2.0 * pi * index / 64),
                first[1] + radius * sin(2.0 * pi * index / 64),
            )
            for index in range(64)
        ]
        set_preview(points, closed=True)

    def _commit(self, sketch, first, second):
        radius = hypot(second[0] - first[0], second[1] - first[1])
        if radius > 0.0:
            sketch.entities.append(SketchCircle(cx=first[0], cy=first[1], radius=radius))


class PARAMETRIC_CAD_OT_draw_arc(_ModalSketchTool, bpy.types.Operator):
    """Draw an arc with center, start, and end clicks."""

    bl_idname = "parametric_cad.draw_arc"
    bl_label = "Arc"
    bl_description = "Draw a circular arc with center, start, and end points"
    bl_options = {"REGISTER", "UNDO", "BLOCKING"}
    snap_points = True

    center: tuple[float, float] | None = None
    start: tuple[float, float] | None = None

    def invoke(self, context, event):
        result = super().invoke(context, event)
        if result == {"RUNNING_MODAL"}:
            self.center = None
            self.start = None
            context.area.header_text_set("CAD: click arc center; Esc cancels")
        return result

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"}:
            self._finish(context)
            return {"CANCELLED"}
        if event.type == "MOUSEMOVE":
            point, sketch = self._point_and_sketch(context, event)
            if point is not None:
                ui = context.scene.parametric_cad_ui
                ui.mouse_x_mm, ui.mouse_y_mm = point[0] * 1000.0, point[1] * 1000.0
            if point is not None and sketch is not None:
                if self.center is None:
                    clear_preview()
                elif self.start is None:
                    set_preview(
                        [
                            sketch_to_world(sketch, *self.center),
                            sketch_to_world(sketch, *point),
                        ]
                    )
                else:
                    self._set_arc_preview(sketch, point)
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            point, sketch = self._point_and_sketch(context, event)
            if point is None or sketch is None:
                return {"RUNNING_MODAL"}
            if self.center is None:
                self.center = point
                context.area.header_text_set("CAD: click arc start point")
                return {"RUNNING_MODAL"}
            if self.start is None:
                if _distance(self.center, point) <= ProfileDetector.tolerance:
                    return {"RUNNING_MODAL"}
                self.start = point
                context.area.header_text_set("CAD: click arc end point")
                return {"RUNNING_MODAL"}
            document = load_document_from_scene(context.scene)
            part = document.active_part
            stored = part.get_feature(sketch.id) if part else None
            if isinstance(stored, SketchFeature):
                self._commit(stored, self.center, self.start, point)
                ui = context.scene.parametric_cad_ui
                ui.active_sketch_entity_id = ""
                ui.active_sketch_entity_ids = "[]"
                ui.sketch_dirty = True
                save_document_to_scene(context.scene, document)
            self._finish(context)
            return {"FINISHED"}
        return {"RUNNING_MODAL"}

    def _set_arc_preview(self, sketch, end):
        points = _arc_points(self.center, self.start, end)
        set_preview([sketch_to_world(sketch, *point) for point in points])

    def _commit(self, sketch, center, start, end):
        start_angle, sweep = _arc_angles(center, start, end)
        if abs(sweep) > ProfileDetector.tolerance:
            _split_line_at_point(sketch, start)
            _split_line_at_point(sketch, end)
            sketch.entities.append(
                SketchArc(
                    cx=center[0],
                    cy=center[1],
                    radius=_distance(center, start),
                    start_angle=start_angle,
                    end_angle=start_angle + sweep,
                )
            )


class PARAMETRIC_CAD_OT_select_tool(bpy.types.Operator):
    bl_idname = "parametric_cad.select_tool"
    bl_label = "Select"
    bl_description = "Select a rectangle, circle, arc, or individual geometry"
    bl_options = {"BLOCKING"}

    def invoke(self, context, _event):
        ui = context.scene.parametric_cad_ui
        if context.area.type != "VIEW_3D" or ui.mode != "SKETCH_EDIT":
            return {"CANCELLED"}
        clear_preview()
        context.window_manager.modal_handler_add(self)
        context.area.header_text_set("CAD: click a Rectangle, Circle, or Arc; Esc cancels")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"}:
            context.area.header_text_set(None)
            return {"CANCELLED"}
        if event.type != "LEFTMOUSE" or event.value != "PRESS":
            return {"RUNNING_MODAL"}

        ui = context.scene.parametric_cad_ui
        document = load_document_from_scene(context.scene)
        part = document.active_part
        sketch = part.get_feature(ui.active_sketch_id) if part else None
        if not isinstance(sketch, SketchFeature):
            context.area.header_text_set(None)
            return {"CANCELLED"}
        try:
            sketch.apply_resolved_plane(resolve_sketch_plane_from_history(part, sketch.id))
        except PlaneResolutionError:
            context.area.header_text_set(None)
            return {"CANCELLED"}
        point = screen_to_sketch(context, event, sketch)
        if point is None:
            return {"RUNNING_MODAL"}
        entity = _nearest_entity(sketch, point)
        if entity is None or self._distance(entity, point) > _selection_tolerance(
            context, event, sketch
        ):
            return {"RUNNING_MODAL"}
        if not _select_entity_dimensions(
            ui, sketch, entity, extend=getattr(event, "shift", False)
        ):
            return {"RUNNING_MODAL"}
        context.area.header_text_set(None)
        tag_redraw()
        return {"FINISHED"}

    @staticmethod
    def _distance(entity, point):
        return _entity_distance(entity, point)


class PARAMETRIC_CAD_OT_edit_sketch_geometry(bpy.types.Operator):
    """Select Sketch geometry from a double-click and expose its dimensions."""

    bl_idname = "parametric_cad.edit_sketch_geometry"
    bl_label = "Edit Sketch Geometry"
    bl_description = "Double-click a circle, rectangle, arc, or line to edit it"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        ui = getattr(context.scene, "parametric_cad_ui", None)
        if (
            ui is None
            or context.area is None
            or context.area.type != "VIEW_3D"
        ):
            return {"CANCELLED"}
        document = load_document_from_scene(context.scene)
        part = document.active_part
        sketch = part.get_feature(ui.active_sketch_id) if part and ui.active_sketch_id else None
        if not isinstance(sketch, SketchFeature) and ui.mode != "SKETCH_EDIT":
            candidate = part.get_feature(ui.active_feature_id) if part else None
            if isinstance(candidate, SketchFeature):
                from .sketch import _begin_edit

                try:
                    _begin_edit(context, part, candidate, False)
                except Exception:
                    return {"CANCELLED"}
                sketch = candidate
        if not isinstance(sketch, SketchFeature):
            return {"CANCELLED"}
        try:
            sketch.apply_resolved_plane(resolve_sketch_plane_from_history(part, sketch.id))
        except PlaneResolutionError:
            return {"CANCELLED"}
        point = screen_to_sketch(context, event, sketch)
        if point is None:
            return {"CANCELLED"}
        entity = _nearest_entity(sketch, point)
        if entity is None or _entity_distance(entity, point) > _selection_tolerance(
            context, event, sketch
        ):
            return {"CANCELLED"}
        if not _select_entity_dimensions(ui, sketch, entity, extend=False):
            return {"CANCELLED"}
        context.area.header_text_set(None)
        tag_redraw()
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_delete_region(_ModalSketchTool, bpy.types.Operator):
    """Mark the bounded region under the cursor as removed from the profile."""

    bl_idname = "parametric_cad.delete_region"
    bl_label = "Delete Region"
    bl_description = "Delete one bounded sketch region; draw a Line across a boundary first"
    bl_options = {"REGISTER", "UNDO", "BLOCKING"}

    def invoke(self, context, event):
        result = super().invoke(context, event)
        if result == {"RUNNING_MODAL"}:
            context.area.header_text_set("CAD: click a region to delete; Esc cancels")
        return result

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"}:
            self._finish(context)
            return {"CANCELLED"}
        if event.type != "LEFTMOUSE" or event.value != "PRESS":
            return {"RUNNING_MODAL"}
        point, sketch = self._point_and_sketch(context, event)
        if point is None or sketch is None:
            return {"RUNNING_MODAL"}
        regions = ProfileDetector().detect_regions(sketch)
        candidates = [
            region
            for region in regions
            if region.region_id not in sketch.deleted_regions
            and ProfileDetector.point_in_loop(point, region)
        ]
        if not candidates:
            self.report({"INFO"}, "Click inside a closed sketch region.")
            self._finish(context)
            return {"FINISHED"}
        region = min(candidates, key=lambda item: abs(ProfileDetector.area(item.points)))
        document = load_document_from_scene(context.scene)
        part = document.active_part
        stored = part.get_feature(sketch.id) if part else None
        if not isinstance(stored, SketchFeature):
            self._finish(context)
            return {"CANCELLED"}
        stored.deleted_regions.append(region.region_id)
        ui = context.scene.parametric_cad_ui
        ui.active_sketch_entity_id = ""
        ui.active_sketch_entity_ids = "[]"
        ui.sketch_dirty = True
        save_document_to_scene(context.scene, document)
        self.report({"INFO"}, "Sketch region deleted from Extrude/Revolve profiles.")
        self._finish(context)
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_delete_geometry(_ModalSketchTool, bpy.types.Operator):
    """Delete one selected sketch entity without removing its neighbors."""

    bl_idname = "parametric_cad.delete_geometry"
    bl_label = "Delete Geometry"
    bl_description = "Delete the selected geometry or click one line, circle, or arc"
    bl_options = {"REGISTER", "UNDO", "BLOCKING"}
    selected_only: bpy.props.BoolProperty(
        name="Selected Only",
        default=False,
        options={"HIDDEN"},
    )

    def invoke(self, context, event):
        if self.selected_only:
            ui = context.scene.parametric_cad_ui
            if context.area.type != "VIEW_3D" or ui.mode != "SKETCH_EDIT":
                return {"CANCELLED"}
            document = load_document_from_scene(context.scene)
            part = document.active_part
            sketch = part.get_feature(ui.active_sketch_id) if part else None
            entity_id = ui.active_sketch_entity_id
            if not isinstance(sketch, SketchFeature) or not entity_id:
                self.report({"INFO"}, "Select a geometry first.")
                return {"CANCELLED"}
            entity = next((item for item in sketch.entities if item.id == entity_id), None)
            if entity is None:
                ui.active_sketch_entity_id = ""
                self.report({"INFO"}, "The selected geometry is no longer available.")
                return {"CANCELLED"}
            stored = part.get_feature(sketch.id) if part else None
            if not isinstance(stored, SketchFeature):
                return {"CANCELLED"}
            _remove_entity(stored, entity.id)
            ui.active_sketch_entity_id = ""
            ui.active_sketch_entity_ids = "[]"
            ui.sketch_dirty = True
            save_document_to_scene(context.scene, document)
            self.report({"INFO"}, f"Deleted {entity.entity_type.title()} geometry.")
            clear_preview()
            tag_redraw()
            return {"FINISHED"}
        result = super().invoke(context, event)
        if result == {"RUNNING_MODAL"}:
            context.area.header_text_set("CAD: click one geometry to delete; Esc cancels")
        return result

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"}:
            self._finish(context)
            return {"CANCELLED"}
        if event.type != "LEFTMOUSE" or event.value != "PRESS":
            return {"RUNNING_MODAL"}
        point, sketch = self._point_and_sketch(context, event)
        if point is None or sketch is None:
            return {"RUNNING_MODAL"}
        entity = _nearest_entity(sketch, point)
        if entity is None or _entity_distance(entity, point) > _selection_tolerance(
            context, event, sketch
        ):
            self.report({"INFO"}, "Click a line, circle, or arc to delete it.")
            self._finish(context)
            return {"FINISHED"}
        document = load_document_from_scene(context.scene)
        part = document.active_part
        stored = part.get_feature(sketch.id) if part else None
        if not isinstance(stored, SketchFeature):
            self._finish(context)
            return {"CANCELLED"}
        _remove_entity(stored, entity.id)
        ui = context.scene.parametric_cad_ui
        ui.active_sketch_entity_id = ""
        ui.active_sketch_entity_ids = "[]"
        ui.sketch_dirty = True
        save_document_to_scene(context.scene, document)
        self.report({"INFO"}, f"Deleted {entity.entity_type.title()} geometry.")
        self._finish(context)
        return {"FINISHED"}


def _distance(first, second) -> float:
    return hypot(first[0] - second[0], first[1] - second[1])


def _arc_angles(center, start, end) -> tuple[float, float]:
    start_angle = atan2(start[1] - center[1], start[0] - center[0])
    end_angle = atan2(end[1] - center[1], end[0] - center[0])
    sweep = (end_angle - start_angle + pi) % (2.0 * pi) - pi
    return start_angle, sweep


def _arc_points(center, start, end, segments: int = 32):
    start_angle, sweep = _arc_angles(center, start, end)
    radius = _distance(center, start)
    return [
        (
            center[0] + radius * cos(start_angle + sweep * index / segments),
            center[1] + radius * sin(start_angle + sweep * index / segments),
        )
        for index in range(segments + 1)
    ]


def _arc_distance(arc: SketchArc, point) -> float:
    angle = atan2(point[1] - arc.cy, point[0] - arc.cx)
    start, sweep = arc.start_angle, arc.end_angle - arc.start_angle
    if abs(sweep) <= ProfileDetector.tolerance:
        sweep = 2.0 * pi
    if sweep >= 0.0:
        relative = (angle - start) % (2.0 * pi)
        in_sweep = relative <= sweep
    else:
        relative = (start - angle) % (2.0 * pi)
        in_sweep = relative <= -sweep
    if in_sweep:
        radial = hypot(point[0] - arc.cx, point[1] - arc.cy)
        return abs(radial - arc.radius)
    return min(_distance(point, arc.start_point), _distance(point, arc.end_point))


def _entity_distance(entity, point) -> float:
    if isinstance(entity, SketchCircle):
        return abs(hypot(point[0] - entity.cx, point[1] - entity.cy) - entity.radius)
    if isinstance(entity, SketchLine):
        dx, dy = entity.x2 - entity.x1, entity.y2 - entity.y1
        length_squared = dx * dx + dy * dy
        if length_squared == 0.0:
            return _distance(point, (entity.x1, entity.y1))
        position = max(
            0.0,
            min(
                1.0,
                ((point[0] - entity.x1) * dx + (point[1] - entity.y1) * dy)
                / length_squared,
            ),
        )
        return _distance(
            point,
            (entity.x1 + position * dx, entity.y1 + position * dy),
        )
    if isinstance(entity, SketchArc):
        return _arc_distance(entity, point)
    return float("inf")


def _nearest_entity(sketch: SketchFeature, point):
    return min(
        (
            entity
            for entity in sketch.entities
            if isinstance(entity, (SketchLine, SketchCircle, SketchArc))
        ),
        key=lambda entity: _entity_distance(entity, point),
        default=None,
    )


def _select_entity_dimensions(ui, sketch: SketchFeature, entity, extend=False) -> bool:
    """Populate transient dimension fields for the selected geometry."""

    if extend and isinstance(entity, SketchCircle):
        try:
            selected = json.loads(ui.active_sketch_entity_ids or "[]")
        except (TypeError, ValueError):
            selected = []
        selected = [item for item in selected if isinstance(item, str)]
        if entity.id not in selected:
            selected.append(entity.id)
        ui.active_sketch_entity_ids = json.dumps(selected, separators=(",", ":"))
    else:
        ui.active_sketch_entity_ids = json.dumps([entity.id])

    if isinstance(entity, SketchCircle):
        parameters = circle_parameters(sketch, entity.id)
        if parameters is None:
            return False
        ui.active_sketch_entity_id = entity.id
        ui.circle_x_mm, ui.circle_y_mm, ui.circle_diameter_mm = (
            value * 1000.0 for value in parameters
        )
        return True
    if isinstance(entity, SketchLine):
        parameters = rectangle_parameters(sketch, entity.id)
        ui.active_sketch_entity_id = entity.id
        if parameters is None:
            return True
        (
            ui.rectangle_x_mm,
            ui.rectangle_y_mm,
            ui.rectangle_width_mm,
            ui.rectangle_height_mm,
        ) = (value * 1000.0 for value in parameters)
        return True
    if isinstance(entity, SketchArc):
        parameters = arc_parameters(sketch, entity.id)
        if parameters is None:
            return False
        ui.active_sketch_entity_id = entity.id
        (
            ui.arc_x_mm,
            ui.arc_y_mm,
            ui.arc_radius_mm,
            ui.arc_start_deg,
            ui.arc_end_deg,
        ) = (
            parameters[0] * 1000.0,
            parameters[1] * 1000.0,
            parameters[2] * 1000.0,
            degrees(parameters[3]),
            degrees(parameters[4]),
        )
        return True
    return False


def _selection_tolerance(context, event, sketch) -> float:
    """Convert a small, zoom-independent screen radius to sketch units."""

    try:
        point = screen_to_sketch(context, event, sketch)
        if point is None:
            return 0.002
        pixel_event = SimpleNamespace(
            mouse_region_x=event.mouse_region_x + 8.0,
            mouse_region_y=event.mouse_region_y,
        )
        offset = screen_to_sketch(context, pixel_event, sketch)
        if offset is not None:
            return max(hypot(offset[0] - point[0], offset[1] - point[1]), 1e-6)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    return 0.002


def _remove_entity(sketch: SketchFeature, entity_id: str) -> None:
    sketch.entities = [item for item in sketch.entities if item.id != entity_id]
    # Region IDs contain boundary UUIDs, so any geometry edit invalidates old
    # exclusions. They must be reselected from the new profile graph.
    sketch.deleted_regions.clear()


def _snap_point(sketch: SketchFeature, point):
    """Snap a sketch point to intersections, vertices, or curve interiors."""

    return snap_point(sketch.entities, point)


def _split_line_at_point(sketch: SketchFeature, point) -> None:
    tolerance = 1e-6
    index = 0
    while index < len(sketch.entities):
        entity = sketch.entities[index]
        if entity.construction or not isinstance(entity, SketchLine):
            index += 1
            continue
        dx, dy = entity.x2 - entity.x1, entity.y2 - entity.y1
        length_squared = dx * dx + dy * dy
        if length_squared <= tolerance * tolerance:
            index += 1
            continue
        position = ((point[0] - entity.x1) * dx + (point[1] - entity.y1) * dy) / length_squared
        if position <= tolerance or position >= 1.0 - tolerance:
            index += 1
            continue
        projected = (entity.x1 + position * dx, entity.y1 + position * dy)
        if _distance(projected, point) > tolerance:
            index += 1
            continue
        old_end = (entity.x2, entity.y2)
        entity.x2, entity.y2 = point
        sketch.entities.insert(
            index + 1,
            SketchLine(x1=point[0], y1=point[1], x2=old_end[0], y2=old_end[1]),
        )
        index += 2


CLASSES = (
    PARAMETRIC_CAD_OT_select_tool,
    PARAMETRIC_CAD_OT_edit_sketch_geometry,
    PARAMETRIC_CAD_OT_draw_line,
    PARAMETRIC_CAD_OT_draw_rectangle,
    PARAMETRIC_CAD_OT_draw_circle,
    PARAMETRIC_CAD_OT_draw_arc,
    PARAMETRIC_CAD_OT_delete_region,
    PARAMETRIC_CAD_OT_delete_geometry,
)
