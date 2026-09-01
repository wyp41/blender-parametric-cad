"""Modal Line, Rectangle, and Circle sketch drawing tools."""

from __future__ import annotations

from math import cos, hypot, pi, sin

import bpy

from ...sketch.entities import SketchCircle, SketchLine
from ...sketch.plane import PlaneResolutionError, resolve_sketch_plane_from_history
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

    def _update_preview(self, sketch, first, second):
        set_preview([sketch_to_world(sketch, *first), sketch_to_world(sketch, *second)])

    def _commit(self, sketch, first, second):
        if first != second:
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


class PARAMETRIC_CAD_OT_select_tool(bpy.types.Operator):
    bl_idname = "parametric_cad.select_tool"
    bl_label = "Select"
    bl_description = "Return to sketch inspection; M2 editing uses Delete All and redraw"

    def execute(self, context):
        clear_preview()
        self.report({"INFO"}, "Direct entity selection is planned for the next milestone")
        return {"FINISHED"}


CLASSES = (
    PARAMETRIC_CAD_OT_select_tool,
    PARAMETRIC_CAD_OT_draw_line,
    PARAMETRIC_CAD_OT_draw_rectangle,
    PARAMETRIC_CAD_OT_draw_circle,
)
