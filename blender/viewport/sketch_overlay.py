"""Lightweight GPU sketch and tool-preview overlay."""

from __future__ import annotations

from math import cos, pi, sin

import bpy
import gpu
from gpu_extras.batch import batch_for_shader

from ...sketch.entities import SketchCircle, SketchLine
from ...sketch.numeric import rectangle_entity_ids
from ...sketch.plane import PlaneResolutionError, resolve_sketch_plane_from_history
from ...sketch.sketch import SketchFeature, sketch_to_world
from ..adapter import load_document_from_scene

_draw_handle = None
_preview_points: list[tuple[float, float, float]] = []
_preview_closed = False


def set_preview(points: list[tuple[float, float, float]], closed: bool = False) -> None:
    global _preview_points, _preview_closed
    _preview_points = points
    _preview_closed = closed
    tag_redraw()


def clear_preview() -> None:
    set_preview([])


def tag_redraw() -> None:
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def start() -> None:
    global _draw_handle
    if _draw_handle is None:
        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_callback, (), "WINDOW", "POST_VIEW"
        )


def stop() -> None:
    global _draw_handle
    if _draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, "WINDOW")
        _draw_handle = None
    clear_preview()


def _draw_callback() -> None:
    scene = bpy.context.scene
    if not hasattr(scene, "parametric_cad_ui"):
        return
    ui = scene.parametric_cad_ui
    try:
        document = load_document_from_scene(scene)
    except (ValueError, TypeError):
        return
    part = document.active_part
    if part is None:
        return
    editing = ui.mode == "SKETCH_EDIT" and bool(ui.active_sketch_id)
    if not editing and not ui.show_sketches:
        return
    limit = part.rollback_index if part.rollback_index is not None else len(part.features) - 1
    for index, sketch in enumerate(part.features):
        if (
            index > limit
            or not isinstance(sketch, SketchFeature)
            or sketch.suppressed
            or (not ui.show_sketches and sketch.id != ui.active_sketch_id)
        ):
            continue
        try:
            sketch.apply_resolved_plane(
                resolve_sketch_plane_from_history(part, sketch.id)
            )
        except PlaneResolutionError:
            continue
        color = (
            (0.15, 0.7, 1.0, 1.0)
            if editing and sketch.id == ui.active_sketch_id
            else (1.0, 0.7, 0.1, 1.0)
            if sketch.id == ui.active_feature_id
            else (0.55, 0.65, 0.72, 0.8)
        )
        selected_ids: set[str] = set()
        if editing and sketch.id == ui.active_sketch_id and ui.active_sketch_entity_id:
            selected_ids = set(
                rectangle_entity_ids(sketch, ui.active_sketch_entity_id)
                or (ui.active_sketch_entity_id,)
            )
        _draw_segments(_entity_segments(sketch, exclude=selected_ids), color, 3.5)
        _draw_segments(
            _entity_segments(sketch, include=selected_ids),
            (1.0, 0.65, 0.1, 1.0),
            5.0,
        )
        if editing and sketch.id == ui.active_sketch_id:
            origin = sketch.origin
            axis_length = 0.02
            x_end = tuple(
                origin[axis] + sketch.x_axis[axis] * axis_length for axis in range(3)
            )
            y_end = tuple(
                origin[axis] + sketch.y_axis[axis] * axis_length for axis in range(3)
            )
            _draw_segments([origin, x_end], (1.0, 0.2, 0.2, 1.0))
            _draw_segments([origin, y_end], (0.2, 1.0, 0.2, 1.0))

    if not editing:
        return
    preview_segments: list[tuple[float, float, float]] = []
    if len(_preview_points) > 1:
        for index in range(len(_preview_points) - 1):
            preview_segments.extend([_preview_points[index], _preview_points[index + 1]])
        if _preview_closed:
            preview_segments.extend([_preview_points[-1], _preview_points[0]])
    _draw_segments(preview_segments, (1.0, 0.65, 0.1, 1.0))


def _entity_segments(
    sketch: SketchFeature,
    include: set[str] | None = None,
    exclude: set[str] | None = None,
) -> list[tuple[float, float, float]]:
    segments: list[tuple[float, float, float]] = []
    for entity in sketch.entities:
        if (include is not None and entity.id not in include) or (
            exclude is not None and entity.id in exclude
        ):
            continue
        if isinstance(entity, SketchLine):
            segments.extend(
                [
                    sketch_to_world(sketch, entity.x1, entity.y1),
                    sketch_to_world(sketch, entity.x2, entity.y2),
                ]
            )
        elif isinstance(entity, SketchCircle):
            points = [
                sketch_to_world(
                    sketch,
                    entity.cx + entity.radius * cos(2.0 * pi * index / 64),
                    entity.cy + entity.radius * sin(2.0 * pi * index / 64),
                )
                for index in range(65)
            ]
            for index in range(64):
                segments.extend([points[index], points[index + 1]])
    return segments


def _draw_segments(points, color, width: float = 3.5) -> None:
    if not points:
        return
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(shader, "LINES", {"pos": points})
    gpu.state.depth_test_set("NONE")
    gpu.state.line_width_set(width)
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.line_width_set(1.0)
    gpu.state.depth_test_set("LESS_EQUAL")
