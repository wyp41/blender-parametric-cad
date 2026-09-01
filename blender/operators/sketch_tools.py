"""Modal sketch drawing, selection, and region editing tools."""

from __future__ import annotations

from math import atan2, cos, degrees, hypot, pi, sin

import bpy

from ...sketch.entities import SketchArc, SketchCircle, SketchLine
from ...sketch.numeric import arc_parameters, circle_parameters, rectangle_parameters
from ...sketch.plane import PlaneResolutionError, resolve_sketch_plane_from_history
from ...sketch.profile import ProfileDetector
from ...sketch.sketch import SketchFeature, sketch_to_world
from ..adapter import load_document_from_scene, save_document_to_scene
from ..viewport.projection import screen_to_sketch
from ..viewport.sketch_overlay import clear_preview, set_preview, tag_redraw


class _ModalSketchTool:
    first_point: tuple[float, float] | None = None

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
                context.scene.parametric_cad_ui.active_sketch_entity_id = ""
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
            return None, None
        return screen_to_sketch(context, event, sketch), sketch

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

    def _point_and_sketch(self, context, event):
        point, sketch = super()._point_and_sketch(context, event)
        if point is not None and sketch is not None:
            point = _snap_point(sketch, point)
        return point, sketch

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
                context.scene.parametric_cad_ui.active_sketch_entity_id = ""
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
    bl_description = "Select a rectangle, circle, or arc to edit its dimensions"
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
        entities = [entity for entity in sketch.entities if not entity.construction]
        entity = min(entities, key=lambda item: self._distance(item, point), default=None)
        if entity is None or self._distance(entity, point) > 0.002:
            return {"RUNNING_MODAL"}
        if isinstance(entity, SketchCircle):
            parameters = circle_parameters(sketch, entity.id)
            ui.active_sketch_entity_id = entity.id
            ui.circle_x_mm, ui.circle_y_mm, ui.circle_diameter_mm = (
                value * 1000.0 for value in parameters
            )
        elif isinstance(entity, SketchLine):
            parameters = rectangle_parameters(sketch, entity.id)
            if parameters is None:
                self.report({"INFO"}, "This Line is not a complete Rectangle.")
                return {"RUNNING_MODAL"}
            ui.active_sketch_entity_id = entity.id
            (
                ui.rectangle_x_mm,
                ui.rectangle_y_mm,
                ui.rectangle_width_mm,
                ui.rectangle_height_mm,
            ) = (value * 1000.0 for value in parameters)
        elif isinstance(entity, SketchArc):
            parameters = arc_parameters(sketch, entity.id)
            if parameters is None:
                return {"RUNNING_MODAL"}
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
        else:
            return {"RUNNING_MODAL"}
        context.area.header_text_set(None)
        tag_redraw()
        return {"FINISHED"}

    @staticmethod
    def _distance(entity, point):
        if isinstance(entity, SketchCircle):
            return abs(hypot(point[0] - entity.cx, point[1] - entity.cy) - entity.radius)
        if isinstance(entity, SketchLine):
            dx, dy = entity.x2 - entity.x1, entity.y2 - entity.y1
            length_squared = dx * dx + dy * dy
            if length_squared == 0.0:
                return hypot(point[0] - entity.x1, point[1] - entity.y1)
            position = max(
                0.0,
                min(
                    1.0,
                    ((point[0] - entity.x1) * dx + (point[1] - entity.y1) * dy)
                    / length_squared,
                ),
            )
            return hypot(
                point[0] - (entity.x1 + position * dx),
                point[1] - (entity.y1 + position * dy),
            )
        if isinstance(entity, SketchArc):
            return _arc_distance(entity, point)
        return float("inf")


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
        context.scene.parametric_cad_ui.active_sketch_entity_id = ""
        save_document_to_scene(context.scene, document)
        self.report({"INFO"}, "Sketch region deleted from Extrude/Revolve profiles.")
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


def _snap_point(sketch: SketchFeature, point):
    """Snap a line endpoint to nearby vertices or line interiors."""

    best = point
    best_distance = 0.0015
    for entity in sketch.entities:
        if entity.construction:
            continue
        candidates = []
        if isinstance(entity, SketchLine):
            candidates.extend(((entity.x1, entity.y1), (entity.x2, entity.y2)))
            dx, dy = entity.x2 - entity.x1, entity.y2 - entity.y1
            length_squared = dx * dx + dy * dy
            if length_squared > 0.0:
                position = max(
                    0.0,
                    min(
                        1.0,
                        ((point[0] - entity.x1) * dx + (point[1] - entity.y1) * dy)
                        / length_squared,
                    ),
                )
                candidates.append(
                    (entity.x1 + position * dx, entity.y1 + position * dy)
                )
        elif isinstance(entity, SketchArc):
            candidates.extend((entity.start_point, entity.end_point))
        for candidate in candidates:
            distance = _distance(point, candidate)
            if distance < best_distance:
                best, best_distance = candidate, distance
    return best


def _split_line_at_point(sketch: SketchFeature, point) -> None:
    tolerance = 1e-6
    for index, entity in enumerate(list(sketch.entities)):
        if entity.construction or not isinstance(entity, SketchLine):
            continue
        dx, dy = entity.x2 - entity.x1, entity.y2 - entity.y1
        length_squared = dx * dx + dy * dy
        if length_squared <= tolerance * tolerance:
            continue
        position = ((point[0] - entity.x1) * dx + (point[1] - entity.y1) * dy) / length_squared
        if position <= tolerance or position >= 1.0 - tolerance:
            continue
        projected = (entity.x1 + position * dx, entity.y1 + position * dy)
        if _distance(projected, point) > tolerance:
            continue
        old_end = (entity.x2, entity.y2)
        entity.x2, entity.y2 = point
        sketch.entities.insert(
            index + 1,
            SketchLine(x1=point[0], y1=point[1], x2=old_end[0], y2=old_end[1]),
        )
        return


CLASSES = (
    PARAMETRIC_CAD_OT_select_tool,
    PARAMETRIC_CAD_OT_draw_line,
    PARAMETRIC_CAD_OT_draw_rectangle,
    PARAMETRIC_CAD_OT_draw_circle,
    PARAMETRIC_CAD_OT_draw_arc,
    PARAMETRIC_CAD_OT_delete_region,
)
