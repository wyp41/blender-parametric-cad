"""Numeric creation and editing of the currently supported sketch profiles."""

from __future__ import annotations

from .entities import SketchCircle, SketchLine
from .profile import ProfileDetector
from .sketch import SketchFeature


def _rectangle_entities(
    sketch: SketchFeature, entity_id: str | None = None
) -> list[SketchLine] | None:
    entities = [entity for entity in sketch.entities if not entity.construction]
    if entity_id is not None:
        selected = next((entity for entity in entities if entity.id == entity_id), None)
        if not isinstance(selected, SketchLine):
            return None
        tolerance = ProfileDetector.tolerance

        def key(point):
            return round(point[0] / tolerance), round(point[1] / tolerance)

        connected: list[SketchLine] = [selected]
        endpoints = {key((selected.x1, selected.y1)), key((selected.x2, selected.y2))}
        remaining = [
            entity
            for entity in entities
            if isinstance(entity, SketchLine) and entity.id != selected.id
        ]
        changed = True
        while changed:
            changed = False
            for line in list(remaining):
                line_endpoints = {key((line.x1, line.y1)), key((line.x2, line.y2))}
                if endpoints & line_endpoints:
                    connected.append(line)
                    endpoints.update(line_endpoints)
                    remaining.remove(line)
                    changed = True
        entities = connected

    result = ProfileDetector().detect_entities(entities)
    if (
        len(entities) != 4
        or not all(isinstance(entity, SketchLine) for entity in entities)
        or not result.success
        or result.profile is None
        or result.profile.kind != "RECTANGLE"
    ):
        return None
    return entities


def rectangle_entity_ids(
    sketch: SketchFeature, entity_id: str | None = None
) -> tuple[str, ...]:
    entities = _rectangle_entities(sketch, entity_id)
    return tuple(entity.id for entity in entities) if entities else ()


def rectangle_parameters(
    sketch: SketchFeature, entity_id: str | None = None
) -> tuple[float, float, float, float] | None:
    entities = _rectangle_entities(sketch, entity_id)
    if entities is None:
        return None
    result = ProfileDetector().detect_entities(entities)
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
    sketch: SketchFeature,
    x: float,
    y: float,
    width: float,
    height: float,
    entity_id: str | None = None,
) -> None:
    if width <= 0.0 or height <= 0.0:
        raise ValueError("Rectangle Width and Height must be greater than zero.")
    entities = [entity for entity in sketch.entities if not entity.construction]
    rectangle = _rectangle_entities(sketch, entity_id)
    if entities and rectangle is None:
        raise ValueError("Select an existing Rectangle to edit its dimensions.")
    corners = [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]
    if not entities:
        rectangle = [SketchLine() for _index in range(4)]
        sketch.entities.extend(rectangle)
    for index, line in enumerate(rectangle):
        start, end = corners[index], corners[(index + 1) % 4]
        line.x1, line.y1, line.x2, line.y2 = *start, *end


def circle_parameters(
    sketch: SketchFeature, entity_id: str | None = None
) -> tuple[float, float, float] | None:
    entities = [entity for entity in sketch.entities if not entity.construction]
    if entity_id is not None:
        entities = [entity for entity in entities if entity.id == entity_id]
    if len(entities) != 1 or not isinstance(entities[0], SketchCircle):
        return None
    circle = entities[0]
    return circle.cx, circle.cy, circle.radius * 2.0


def set_circle(
    sketch: SketchFeature,
    x: float,
    y: float,
    diameter: float,
    entity_id: str | None = None,
) -> None:
    if diameter <= 0.0:
        raise ValueError("Circle Diameter must be greater than zero.")
    entities = [entity for entity in sketch.entities if not entity.construction]
    if entity_id is not None:
        circle = next((entity for entity in entities if entity.id == entity_id), None)
        if not isinstance(circle, SketchCircle):
            raise ValueError("Select an existing Circle to edit its dimensions.")
    elif entities:
        if len(entities) != 1 or not isinstance(entities[0], SketchCircle):
            raise ValueError("Select an existing Circle to edit its dimensions.")
        circle = entities[0]
    else:
        circle = SketchCircle()
        sketch.entities.append(circle)
    circle.cx, circle.cy, circle.radius = x, y, diameter / 2.0
