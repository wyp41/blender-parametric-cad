"""Screen-space Sketch entity selection shared by tools and overlays."""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, hypot, pi, sin
from typing import Any

from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Vector

from ...core.references import SketchEntityReference
from ...sketch.entities import SketchArc, SketchCircle, SketchLine
from ...sketch.sketch import SketchFeature, sketch_to_world


@dataclass(frozen=True)
class SketchSelectionCandidate:
    """Runtime-only hit candidate; never part of CAD JSON."""

    reference: SketchEntityReference
    local_point: tuple[float, float]
    distance_px: float
    priority: int
    kind: str

    @property
    def entity_id(self) -> str:
        return self.reference.entity_id


def _project(context, sketch: SketchFeature, point: tuple[float, float]):
    region = getattr(context, "region", None)
    region_3d = getattr(getattr(context, "space_data", None), "region_3d", None)
    if region is None or region_3d is None:
        return None
    try:
        return location_3d_to_region_2d(region, region_3d, sketch_to_world(sketch, *point))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None


def _screen_distance(position, event) -> float:
    if position is None:
        return float("inf")
    return hypot(
        float(position.x) - float(getattr(event, "mouse_region_x", 0.0)),
        float(position.y) - float(getattr(event, "mouse_region_y", 0.0)),
    )


def _line_nearest(entity: SketchLine, point: tuple[float, float]) -> tuple[float, float]:
    dx, dy = entity.x2 - entity.x1, entity.y2 - entity.y1
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-24:
        return entity.x1, entity.y1
    position = max(
        0.0,
        min(
            1.0,
            ((point[0] - entity.x1) * dx + (point[1] - entity.y1) * dy)
            / length_squared,
        ),
    )
    return entity.x1 + position * dx, entity.y1 + position * dy


def _arc_nearest(entity: SketchArc, point: tuple[float, float]) -> tuple[float, float]:
    angle = atan2(point[1] - entity.cy, point[0] - entity.cx)
    start, sweep = entity.start_angle, entity.end_angle - entity.start_angle
    if abs(sweep) <= 1e-7:
        sweep = 2.0 * pi
    if sweep >= 0.0:
        relative = (angle - start) % (2.0 * pi)
        in_sweep = relative <= sweep
    else:
        relative = (start - angle) % (2.0 * pi)
        in_sweep = relative <= -sweep
    if in_sweep:
        return entity.point(angle)
    first, second = entity.start_point, entity.end_point
    return first if hypot(point[0] - first[0], point[1] - first[1]) <= hypot(
        point[0] - second[0], point[1] - second[1]
    ) else second


def _entity_nearest_point(entity, point: tuple[float, float]) -> tuple[float, float]:
    if isinstance(entity, SketchLine):
        return _line_nearest(entity, point)
    if isinstance(entity, SketchCircle):
        dx, dy = point[0] - entity.cx, point[1] - entity.cy
        length = hypot(dx, dy)
        if length <= 1e-12:
            return entity.cx + entity.radius, entity.cy
        return entity.cx + entity.radius * dx / length, entity.cy + entity.radius * dy / length
    if isinstance(entity, SketchArc):
        return _arc_nearest(entity, point)
    return point


def _candidate(
    context,
    event,
    sketch: SketchFeature,
    reference: SketchEntityReference,
    local_point: tuple[float, float],
    priority: int,
    kind: str,
) -> SketchSelectionCandidate:
    return SketchSelectionCandidate(
        reference=reference,
        local_point=local_point,
        distance_px=_screen_distance(_project(context, sketch, local_point), event),
        priority=priority,
        kind=kind,
    )


def selection_candidates(
    context,
    event,
    sketch: SketchFeature,
    local_point: tuple[float, float],
) -> list[SketchSelectionCandidate]:
    """Build endpoint/center and whole-entity candidates in screen space.

    Priority 0 is reserved for point sub-elements.  This makes a click near a
    line endpoint or circle center deterministic even when the curve itself is
    also within the pixel tolerance.
    """

    candidates: list[SketchSelectionCandidate] = []
    for entity in sketch.entities:
        if isinstance(entity, SketchLine):
            candidates.extend(
                (
                    _candidate(
                        context,
                        event,
                        sketch,
                        SketchEntityReference(sketch.id, entity.id, "START"),
                        (entity.x1, entity.y1),
                        0,
                        "START",
                    ),
                    _candidate(
                        context,
                        event,
                        sketch,
                        SketchEntityReference(sketch.id, entity.id, "END"),
                        (entity.x2, entity.y2),
                        0,
                        "END",
                    ),
                )
            )
        elif isinstance(entity, SketchCircle):
            candidates.append(
                _candidate(
                    context,
                    event,
                    sketch,
                    SketchEntityReference(sketch.id, entity.id, "CENTER"),
                    (entity.cx, entity.cy),
                    0,
                    "CENTER",
                )
            )
        elif isinstance(entity, SketchArc):
            candidates.extend(
                (
                    _candidate(
                        context,
                        event,
                        sketch,
                        SketchEntityReference(sketch.id, entity.id, "START"),
                        entity.start_point,
                        0,
                        "START",
                    ),
                    _candidate(
                        context,
                        event,
                        sketch,
                        SketchEntityReference(sketch.id, entity.id, "END"),
                        entity.end_point,
                        0,
                        "END",
                    ),
                )
            )
        nearest = _entity_nearest_point(entity, local_point)
        candidates.append(
            _candidate(
                context,
                event,
                sketch,
                SketchEntityReference(sketch.id, entity.id, "ENTITY"),
                nearest,
                1,
                "ENTITY",
            )
        )
    return candidates


def nearest_candidate(
    context,
    event,
    sketch: SketchFeature,
    local_point: tuple[float, float],
    radius_px: float,
) -> SketchSelectionCandidate | None:
    candidates = [
        candidate
        for candidate in selection_candidates(context, event, sketch, local_point)
        if candidate.distance_px <= radius_px
    ]
    return min(candidates, key=lambda item: (item.priority, item.distance_px), default=None)


def selected_references(ui) -> list[SketchEntityReference]:
    import json

    try:
        values = json.loads(ui.active_sketch_references or "[]")
    except (TypeError, ValueError):
        values = []
    references: list[SketchEntityReference] = []
    for value in values if isinstance(values, list) else []:
        try:
            references.append(
                value if isinstance(value, SketchEntityReference)
                else SketchEntityReference.from_dict(value)
            )
        except (TypeError, ValueError):
            continue
    return references


def set_selected_references(ui, references: list[SketchEntityReference]) -> None:
    import json

    ui.active_sketch_references = json.dumps(
        [reference.to_dict() for reference in references],
        separators=(",", ":"),
    )
    entity_ids: list[str] = []
    for reference in references:
        if reference.entity_id not in entity_ids:
            entity_ids.append(reference.entity_id)
    ui.active_sketch_entity_ids = json.dumps(entity_ids, separators=(",", ":"))
    ui.active_sketch_entity_id = entity_ids[0] if entity_ids else ""


def reference_local_point(
    sketch: SketchFeature, reference: SketchEntityReference
) -> tuple[float, float] | None:
    entity = next((item for item in sketch.entities if item.id == reference.entity_id), None)
    if entity is None:
        return None
    if isinstance(entity, SketchLine):
        if reference.sub_element == "START":
            return entity.x1, entity.y1
        if reference.sub_element == "END":
            return entity.x2, entity.y2
    if isinstance(entity, SketchCircle) and reference.sub_element == "CENTER":
        return entity.cx, entity.cy
    if isinstance(entity, SketchArc):
        if reference.sub_element == "START":
            return entity.start_point
        if reference.sub_element == "END":
            return entity.end_point
        if reference.sub_element == "CENTER":
            return entity.cx, entity.cy
    return None


def nearest_dimension(context, event, sketch: SketchFeature, dimensions, radius_px: float):
    """Return a dimension whose label is under the cursor, if any."""

    from ...sketch.dimensions import dimension_label_point, validate_dimension

    hits = []
    for dimension in dimensions:
        try:
            point = dimension_label_point(sketch, dimension)
            position = _project(context, sketch, point)
            distance = _screen_distance(position, event)
            if distance <= radius_px * 1.5:
                hits.append((distance, dimension))
        except (TypeError, ValueError):
            continue
    return min(hits, key=lambda item: item[0])[1] if hits else None
