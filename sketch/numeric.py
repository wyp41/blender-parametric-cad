"""Numeric creation and editing of the currently supported sketch profiles."""

from __future__ import annotations

from .entities import SketchCircle, SketchLine
from .profile import ProfileDetector
from .sketch import SketchFeature


def rectangle_parameters(sketch: SketchFeature) -> tuple[float, float, float, float] | None:
    entities = [entity for entity in sketch.entities if not entity.construction]
    result = ProfileDetector().detect(sketch)
    if (
        len(entities) != 4
        or not all(isinstance(entity, SketchLine) for entity in entities)
        or not result.success
        or result.profile is None
        or result.profile.kind != "RECTANGLE"
    ):
        return None
    points = result.profile.points
    left = min(point[0] for point in points)
    bottom = min(point[1] for point in points)
    return (
        left,
        bottom,
        max(point[0] for point in points) - left,
        max(point[1] for point in points) - bottom,
    )


def set_rectangle(
    sketch: SketchFeature, x: float, y: float, width: float, height: float
) -> None:
    if width <= 0.0 or height <= 0.0:
        raise ValueError("Rectangle Width and Height must be greater than zero.")
    entities = [entity for entity in sketch.entities if not entity.construction]
    if entities and rectangle_parameters(sketch) is None:
        raise ValueError("Numeric Rectangle requires an empty Sketch or one Rectangle.")
    corners = [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]
    if not entities:
        entities = [SketchLine() for _index in range(4)]
        sketch.entities.extend(entities)
    for index, line in enumerate(entities):
        start, end = corners[index], corners[(index + 1) % 4]
        line.x1, line.y1, line.x2, line.y2 = *start, *end


def circle_parameters(sketch: SketchFeature) -> tuple[float, float, float] | None:
    entities = [entity for entity in sketch.entities if not entity.construction]
    if len(entities) != 1 or not isinstance(entities[0], SketchCircle):
        return None
    circle = entities[0]
    return circle.cx, circle.cy, circle.radius * 2.0


def set_circle(sketch: SketchFeature, x: float, y: float, diameter: float) -> None:
    if diameter <= 0.0:
        raise ValueError("Circle Diameter must be greater than zero.")
    entities = [entity for entity in sketch.entities if not entity.construction]
    if entities and circle_parameters(sketch) is None:
        raise ValueError("Numeric Circle requires an empty Sketch or one Circle.")
    if entities:
        circle = entities[0]
    else:
        circle = SketchCircle()
        sketch.entities.append(circle)
    circle.cx, circle.cy, circle.radius = x, y, diameter / 2.0
