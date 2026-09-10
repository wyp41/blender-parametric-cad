"""Numeric creation and editing of the currently supported sketch profiles."""

from __future__ import annotations

from .entities import SketchArc, SketchCircle, SketchLine
from .primitives import RectangleDefinition
from .profile import ProfileDetector
from .sketch import SketchFeature


def _rectangle_entities(
    sketch: SketchFeature, entity_id: str | None = None
) -> list[SketchLine] | None:
    definition = rectangle_definition_for(sketch, entity_id)
    if definition is not None:
        by_id = {entity.id: entity for entity in sketch.entities}
        ordered = [by_id.get(item_id) for item_id in definition.entity_ids]
        if all(isinstance(item, SketchLine) and not item.construction for item in ordered):
            return [item for item in ordered if isinstance(item, SketchLine)]
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
        # Keep the Sketch's original entity order.  The selected line only
        # identifies the rectangle; it must not rotate the UUID-to-edge
        # mapping when dimensions are edited.  Persistent face references may
        # point at any one of those line UUIDs.
        connected_ids = {entity.id for entity in connected}
        entities = [entity for entity in entities if entity.id in connected_ids]

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


def rectangle_definition_for(
    sketch: SketchFeature, entity_id: str | None = None, rectangle_id: str | None = None
) -> RectangleDefinition | None:
    """Return the persistent rectangle containing an entity or matching UUID."""

    if rectangle_id:
        return next(
            (item for item in sketch.rectangles if item.id == str(rectangle_id)),
            None,
        )
    if entity_id:
        return next(
            (item for item in sketch.rectangles if item.contains_entity(str(entity_id))),
            None,
        )
    return sketch.rectangles[0] if len(sketch.rectangles) == 1 else None


def _ensure_rectangle_definition(
    sketch: SketchFeature, entities: list[SketchLine]
) -> RectangleDefinition:
    existing = next(
        (
            item
            for item in sketch.rectangles
            if tuple(item.entity_ids) == tuple(entity.id for entity in entities)
        ),
        None,
    )
    if existing is not None:
        return existing
    definition = RectangleDefinition(
        bottom_line_id=entities[0].id,
        right_line_id=entities[1].id,
        top_line_id=entities[2].id,
        left_line_id=entities[3].id,
    )
    sketch.rectangles.append(definition)
    return definition


def remove_rectangle_definitions_for_entities(
    sketch: SketchFeature, entity_ids: set[str] | list[str] | tuple[str, ...]
) -> int:
    """Remove semantic rectangles that would retain deleted line UUIDs."""

    wanted = {str(item) for item in entity_ids}
    before = len(sketch.rectangles)
    sketch.rectangles = [
        item for item in sketch.rectangles if not wanted.intersection(item.entity_ids)
    ]
    return before - len(sketch.rectangles)


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


def rectangle_parameters_by_id(
    sketch: SketchFeature, rectangle_id: str
) -> tuple[float, float, float, float] | None:
    """Read corner-origin parameters for one persistent rectangle UUID."""

    definition = rectangle_definition_for(sketch, rectangle_id=rectangle_id)
    if definition is None:
        return None
    entities = _rectangle_entities(sketch, definition.bottom_line_id)
    if entities is None:
        return None
    result = ProfileDetector().detect_entities(entities)
    if not result.success or result.profile is None:
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
    if rectangle is None or len(rectangle) != 4:
        raise ValueError("Select an existing Rectangle to edit its dimensions.")
    for index, line in enumerate(rectangle):
        start, end = corners[index], corners[(index + 1) % 4]
        line.x1, line.y1, line.x2, line.y2 = *start, *end
    definition = _ensure_rectangle_definition(sketch, rectangle)
    if definition.width_dimension_id:
        dimension = next(
            (item for item in sketch.dimensions if item.id == definition.width_dimension_id),
            None,
        )
        if dimension is not None:
            dimension.value = float(width)
    if definition.height_dimension_id:
        dimension = next(
            (item for item in sketch.dimensions if item.id == definition.height_dimension_id),
            None,
        )
        if dimension is not None:
            dimension.value = float(height)


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


def arc_parameters(
    sketch: SketchFeature, entity_id: str | None = None
) -> tuple[float, float, float, float, float] | None:
    entities = [entity for entity in sketch.entities if not entity.construction]
    if entity_id is not None:
        entities = [entity for entity in entities if entity.id == entity_id]
    if len(entities) != 1 or not isinstance(entities[0], SketchArc):
        return None
    arc = entities[0]
    return arc.cx, arc.cy, arc.radius, arc.start_angle, arc.end_angle


def set_arc(
    sketch: SketchFeature,
    x: float,
    y: float,
    radius: float,
    start_angle: float,
    end_angle: float,
    entity_id: str | None = None,
) -> None:
    if radius <= 0.0:
        raise ValueError("Arc Radius must be greater than zero.")
    entities = [entity for entity in sketch.entities if not entity.construction]
    if entity_id is not None:
        arc = next((entity for entity in entities if entity.id == entity_id), None)
        if not isinstance(arc, SketchArc):
            raise ValueError("Select an existing Arc to edit its dimensions.")
    elif entities:
        if len(entities) != 1 or not isinstance(entities[0], SketchArc):
            raise ValueError("Select an existing Arc to edit its dimensions.")
        arc = entities[0]
    else:
        arc = SketchArc()
        sketch.entities.append(arc)
    if abs(end_angle - start_angle) <= ProfileDetector.tolerance:
        raise ValueError("Arc start and end angles must be different.")
    arc.cx, arc.cy, arc.radius = x, y, radius
    arc.start_angle, arc.end_angle = start_angle, end_angle
