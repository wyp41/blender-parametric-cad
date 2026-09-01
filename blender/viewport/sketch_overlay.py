"""Lightweight GPU sketch and tool-preview overlay."""

from __future__ import annotations

from math import ceil, cos, pi, sin

import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from ...sketch.entities import SketchArc, SketchCircle, SketchLine
from ...sketch.numeric import rectangle_entity_ids
from ...sketch.plane import PlaneResolutionError, resolve_sketch_plane_from_history
from ...sketch.profile import ProfileDetector
from ...sketch.snapping import snap_targets
from ...sketch.sketch import SketchFeature, sketch_to_world
from ..adapter import load_document_from_scene
from .provenance import get_face_provenance

_draw_handle = None
_preview_points: list[tuple[float, float, float]] = []
_preview_closed = False
_snap_preview: tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
] | None = None
_hover_face = None
_selected_face = None


def set_preview(points: list[tuple[float, float, float]], closed: bool = False) -> None:
    global _preview_points, _preview_closed
    _preview_points = points
    _preview_closed = closed
    tag_redraw()


def clear_preview() -> None:
    global _preview_points, _preview_closed, _snap_preview
    _preview_points = []
    _preview_closed = False
    _snap_preview = None
    tag_redraw()


def set_snap_preview(
    point: tuple[float, float, float] | None,
    axes: tuple[tuple[float, float, float], tuple[float, float, float]] | None = None,
    snapped: bool = True,
) -> None:
    """Show a transient marker at the point a drawing tool will use."""

    global _snap_preview
    if point is None or not snapped:
        _snap_preview = None
    else:
        x_axis, y_axis = axes or ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
        _snap_preview = (point, x_axis, y_axis)
    tag_redraw()


def clear_snap_preview() -> None:
    global _snap_preview
    _snap_preview = None
    tag_redraw()


def set_face_hover(hit) -> None:
    global _hover_face
    _hover_face = hit
    tag_redraw()


def set_face_selection(hit) -> None:
    global _selected_face
    _selected_face = hit
    tag_redraw()


def clear_face_selection() -> None:
    global _hover_face, _selected_face
    _hover_face = None
    _selected_face = None
    tag_redraw()


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
    hover_color = (
        (0.15, 0.55, 1.0, 0.22)
        if _hover_face is not None and _hover_face[2] is not None
        else (0.45, 0.45, 0.45, 0.16)
    )
    _draw_face_highlight(_hover_face, hover_color)
    _draw_face_highlight(_selected_face, (1.0, 0.65, 0.1, 0.30))
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
        hidden_ids = _deleted_region_entity_ids(sketch)
        _draw_segments(
            _entity_segments(sketch, exclude=selected_ids | hidden_ids),
            color,
            4.5 if editing and sketch.id == ui.active_sketch_id else 3.5,
        )
        selected_ids -= hidden_ids
        _draw_segments(
            _entity_segments(sketch, include=selected_ids),
            (1.0, 0.65, 0.1, 1.0),
            6.0,
        )
        if editing and sketch.id == ui.active_sketch_id:
            _draw_intersection_markers(sketch, hidden_ids)
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

    if editing and _snap_preview is not None:
        _draw_snap_preview()

    if not editing:
        return
    preview_segments: list[tuple[float, float, float]] = []
    if len(_preview_points) > 1:
        for index in range(len(_preview_points) - 1):
            preview_segments.extend([_preview_points[index], _preview_points[index + 1]])
        if _preview_closed:
            preview_segments.extend([_preview_points[-1], _preview_points[0]])
    _draw_segments(preview_segments, (1.0, 0.65, 0.1, 1.0))


def _draw_face_highlight(hit, color) -> None:
    if hit is None:
        return
    obj, polygon_index, reference = hit
    try:
        mesh = getattr(obj, "data", None)
        if reference is not None:
            polygon_index = _current_polygon_index(obj, polygon_index, reference)
            if polygon_index is None:
                return
        if mesh is None or polygon_index < 0 or polygon_index >= len(mesh.polygons):
            return
        polygon = mesh.polygons[polygon_index]
        if len(polygon.vertices) < 3:
            return
        points = [
            tuple(obj.matrix_world @ Vector(mesh.vertices[index].co))
            for index in polygon.vertices
        ]
    except ReferenceError:
        return
    triangles = []
    for index in range(1, len(points) - 1):
        triangles.extend((points[0], points[index], points[index + 1]))
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(shader, "TRIS", {"pos": triangles})
    gpu.state.depth_test_set("LESS_EQUAL")
    gpu.state.blend_set("ALPHA")
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.blend_set("NONE")
    gpu.state.depth_test_set("LESS_EQUAL")


def _current_polygon_index(obj, fallback: int, reference) -> int | None:
    data = get_face_provenance(obj)
    if fallback in data and data[fallback] == reference:
        return fallback
    for index, candidate in data.items():
        if candidate == reference:
            return index
    return None


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
        elif isinstance(entity, SketchArc):
            sweep = entity.end_angle - entity.start_angle
            if abs(sweep) <= 1e-7:
                sweep = 2.0 * pi
            count = max(8, int(ceil(abs(sweep) * 12.0 / pi)))
            points = [
                sketch_to_world(
                    sketch,
                    *entity.point(entity.start_angle + sweep * index / count),
                )
                for index in range(count + 1)
            ]
            for index in range(count):
                segments.extend([points[index], points[index + 1]])
    return segments


def _deleted_region_entity_ids(sketch: SketchFeature) -> set[str]:
    """Return boundary entities unique to deleted regions.

    Shared edges remain visible when they still bound an active region; only
    the deleted region's outer-only contour is hidden from the sketch overlay.
    """

    if not sketch.deleted_regions:
        return set()
    detector = ProfileDetector()
    deleted: set[str] = set()
    for region in detector.detect_regions(sketch):
        if region.region_id not in sketch.deleted_regions:
            continue
        deleted.update(_loop_entity_ids(region))
    active_result = detector.detect(sketch)
    active: set[str] = set()
    if active_result.success and active_result.profile is not None:
        for loop in active_result.profile.iter_loops():
            active.update(_loop_entity_ids(loop))
    return deleted - active


def _loop_entity_ids(loop) -> set[str]:
    ids = set(loop.entity_ids)
    if not ids and loop.region_id.startswith("REGION:"):
        ids.update(item for item in loop.region_id[7:].split(",") if item)
    return ids


def _draw_intersection_markers(sketch: SketchFeature, hidden_ids: set[str]) -> None:
    entities = [
        entity
        for entity in sketch.entities
        if not entity.construction and entity.id not in hidden_ids
    ]
    points = snap_targets(entities)
    if not points:
        return
    segments: list[tuple[float, float, float]] = []
    size = 0.0012
    for u, v in points:
        center = sketch_to_world(sketch, u, v)
        x_axis = tuple(sketch.x_axis[index] * size for index in range(3))
        y_axis = tuple(sketch.y_axis[index] * size for index in range(3))
        segments.extend(
            [
                tuple(center[index] - x_axis[index] for index in range(3)),
                tuple(center[index] + x_axis[index] for index in range(3)),
                tuple(center[index] - y_axis[index] for index in range(3)),
                tuple(center[index] + y_axis[index] for index in range(3)),
            ]
        )
    _draw_segments(segments, (1.0, 0.85, 0.1, 1.0), 5.0)


def _draw_snap_preview() -> None:
    if _snap_preview is None:
        return
    size = 0.0015
    point, x_axis, y_axis = _snap_preview
    x_offset = tuple(value * size for value in x_axis)
    y_offset = tuple(value * size for value in y_axis)
    segments = [
        (
            point,
            tuple(point[index] + x_offset[index] for index in range(3)),
        ),
        (
            point,
            tuple(point[index] - x_offset[index] for index in range(3)),
        ),
        (
            point,
            tuple(point[index] + y_offset[index] for index in range(3)),
        ),
        (
            point,
            tuple(point[index] - y_offset[index] for index in range(3)),
        ),
    ]
    flattened = [item for segment in segments for item in segment]
    _draw_segments(flattened, (0.25, 1.0, 0.35, 1.0), 6.0)


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
